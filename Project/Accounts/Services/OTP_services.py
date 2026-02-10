# apps/auth/Services/OTP_services.py
import requests
import structlog
from django.conf import settings
from ..utils import auth_utils
import uuid

logger = structlog.get_logger(__name__)


class DiditVerificationService:
    """
    Integration service with Didit V2 - Adapted version without resend
    Documentation: https://docs.didit.me
    Note: Didit does not offer a resend endpoint, we must send a new code
    """
    BASE_URL = "https://verification.didit.me/v3"
    SEND_CODE_URL = f"{BASE_URL}/phone/send"
    VERIFY_CODE_URL = f"{BASE_URL}/phone/check"
    # NO RESEND_CODE_URL - Didit does not offer this functionality

    def __init__(self):
        if not settings.DIDIT_API_KEY:
            raise ValueError("DIDIT_API_KEY is not configured in settings")
        
        self.api_key = settings.DIDIT_API_KEY
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-api-key": self.api_key, 
        }
        self.timeout = 15

    def send_verification_code(self, phone_number, request_meta=None, vendor_data=None):
        """
        Sends an OTP code via Didit.
        
        Args:
            phone_number: E.164 format (e.g.: +33612345678)
            request_meta: Request metadata
            vendor_data: Internal identifier for correlation
        
        Returns:
            dict: Result of the send with request_id
        """
        # E.164 format validation
        if not auth_utils.validate_e164_format(phone_number):
            logger.error("invalid_e164_format", phone_number=auth_utils.mask_phone(phone_number))
            return self._error_response(
                "InvalidFormat", 
                "invalid_phone_format", 
                "Invalid number format"
            )
        
        payload = {
            "phone_number": phone_number,
            "options": {
                "code_size": 6,
                "locale": "fr-FR",
                "preferred_channel": "sms"
            }
        }

        # Add anti-fraud signals
        if request_meta:
            signals = self._extract_signals(request_meta)
            if self._are_signals_valid(signals):
                payload["signals"] = signals
            else:
                logger.warning(
                    "didit_signals_incomplete",
                    phone_number=auth_utils.mask_phone(phone_number),
                    missing_fields=self._get_missing_signal_fields(signals)
                )

        if vendor_data:
            payload["vendor_data"] = str(vendor_data)[:100]

        logger.info(
            "didit_send_code_attempt",
            phone_number=auth_utils.mask_phone(phone_number),
            has_signals="signals" in payload,
            vendor_data=vendor_data[:20] if vendor_data else None
        )

        try:
            response = requests.post(
                self.SEND_CODE_URL,
                json=payload,
                headers=self.headers,
                timeout=self.timeout
            )
            
            logger.debug(
                "didit_send_code_http",
                status_code=response.status_code,
                phone_number=auth_utils.mask_phone(phone_number)
            )
            
            response_data = response.json() if response.content else {}

            if response.status_code == 200:
                return self._handle_success_send(response_data)
            else:
                return self._handle_error_send(response.status_code, response_data)

        except requests.exceptions.Timeout:
            logger.error("didit_send_timeout", phone_number=auth_utils.mask_phone(phone_number))
            return self._error_response(
                "Timeout", 
                "request_timeout", 
                "Service is temporarily unavailable"
            )
        except requests.exceptions.RequestException as e:
            logger.error("didit_send_network_error", error=str(e))
            return self._error_response(
                "NetworkError", 
                "service_unavailable", 
                "Service temporarily unavailable"
            )
        except ValueError as e:
            logger.error("didit_send_json_error", error=str(e))
            return self._error_response(
                "ParseError", 
                "invalid_response", 
                "Invalid response from service"
            )

    def verify_code(self, phone_number, code, request_id=None):
        """
        Verifies an OTP code with Didit.
        
        Args:
            phone_number: E.164 format
            code: OTP code (6 digits)
            request_id: Optional - Didit request ID for tracking
        
        Returns:
            dict: Verification result with details
        """
        # Input validation
        if not auth_utils.validate_e164_format(phone_number):
            return {
                "success": False,
                "verified": False,
                "message": "Invalid number format",
                "code": "invalid_phone_format"
            }
        
        if not code or not code.isdigit() or len(code) != 6:
            return {
                "success": False,
                "verified": False,
                "message": "Invalid OTP code (6 digits required)",
                "code": "invalid_otp_format"
            }

        payload = {
            "phone_number": phone_number,
            "code": code,
        }
        
        # Add request_id if available (often required in prod for exact matching)
        if request_id:
            payload["verification_id"] = request_id

        logger.info(
            "didit_verify_attempt",
            phone_number=auth_utils.mask_phone(phone_number),
            request_id=request_id[:20] if request_id else None,
            code_length=len(code)
        )

        try:
            response = requests.post(
                self.VERIFY_CODE_URL,
                json=payload,
                headers=self.headers,
                timeout=10
            )
            
            logger.debug(
                "didit_verify_http",
                status_code=response.status_code,
                phone_number=auth_utils.mask_phone(phone_number),
                response_body=response.text[:1000]  # Log body for debug
            )
            
            response_data = response.json() if response.content else {}

            if response.status_code != 200:
                logger.error("didit_verify_failed_status", status=response.status_code, body=response_data)
            # Didit v3 response: status is at top level, phone details nested under "phone"
            status = response_data.get("status", "Unknown")
            verified = (status == "Approved")
            phone_details = response_data.get("phone") or {}

            return {
                "success": True,
                "verified": verified,
                "status": status,
                "message": response_data.get("message", "Verification completed"),
                "phone_details": self._extract_phone_details(phone_details)
            }

        except requests.exceptions.Timeout:
            logger.error("didit_verify_timeout", phone_number=auth_utils.mask_phone(phone_number))
            return {"success": False, "verified": False, "message": "Verification timeout"}
        except requests.exceptions.RequestException as e:
            logger.error("didit_verify_network_error", error=str(e))
            return {"success": False, "verified": False, "message": "Network error"}
        except ValueError as e:
            logger.error("didit_verify_json_error", error=str(e))
            return {"success": False, "verified": False, "message": "Invalid response"}

    # === Private utility methods ===

    def _handle_success_send(self, data):
        """Processes a successful code send response."""
        status = data.get("status")
        request_id = data.get("request_id")
        
        if status == "Success":
            return {
                "success": True,
                "request_id": request_id,
                "status": status,
                "message": "Verification code sent by SMS"
            }
        else:
            reason = data.get("reason", "unknown")
            return {
                "success": False,
                "request_id": request_id,
                "status": status,
                "reason": reason,
                "message": self._friendly_message(status, reason)
            }

    def _handle_error_send(self, status_code, data):
        """Processes HTTP errors during sending."""
        error_messages = {
            400: ("BadRequest", "invalid_request", "Invalid request to Didit"),
            401: ("Unauthorized", "invalid_key", "Invalid Didit API Key"),
            403: ("Forbidden", "permission_denied", "Access denied to Didit API"),
            429: ("RateLimited", "rate_limited", "Too many requests to Didit"),
            500: ("ServerError", "didit_server_error", "Internal error at Didit"),
            502: ("BadGateway", "bad_gateway", "Connection problem to Didit"),
            503: ("ServiceUnavailable", "service_unavailable", "Didit temporarily unavailable"),
        }
        
        if status_code in error_messages:
            status, reason, default_message = error_messages[status_code]
            message = data.get("detail") or data.get("message") or default_message
            return self._error_response(status, reason, message)
        else:
            message = data.get("detail") or data.get("message") or f"Didit error ({status_code})"
            return self._error_response("HttpError", "http_error", message)

    def _handle_verification_error(self, status_code, data):
        """Processes HTTP errors during verification."""
        if status_code == 400:
            return {
                "success": False,
                "verified": False,
                "message": data.get("detail", "Invalid verification request"),
                "code": "verification_failed"
            }
        elif status_code == 429:
            return {
                "success": False,
                "verified": False,
                "message": "Too many verification attempts",
                "code": "verification_rate_limited",
                "retry_after": 60
            }
        else:
            return {
                "success": False,
                "verified": False,
                "message": f"Error during verification ({status_code})",
                "code": "verification_error"
            }

    def _error_response(self, status, reason, message):
        """Standard format for error responses."""
        return {
            "success": False,
            "status": status,
            "reason": reason,
            "message": message
        }

    def _extract_signals(self, request_meta):
        """
        Extracts anti-fraud signals from request metadata.
        Format expected by Didit: https://docs.didit.me/reference/phone-verification-signals
        """
        signals = {}
        
        # Field mapping
        mapping = {
            'device_id': 'device_id',
            'app_version': 'app_version',
            'ip': 'client_ip',
            'user_agent': 'user_agent',
        }
        
        for signal_key, meta_key in mapping.items():
            value = request_meta.get(meta_key, '').strip()
            
            # Intelligent default values
            if not value:
                if signal_key == 'device_id':
                    value = f"web_{uuid.uuid4().hex[:8]}"
                elif signal_key == 'app_version':
                    value = "1.0.0"
                elif signal_key == 'ip':
                    # Never set to 0.0.0.0, use real IP or 'unknown'
                    value = request_meta.get('client_ip', 'unknown')[:50]
                elif signal_key == 'user_agent':
                    value = "Unknown"
            
            if value:
                signals[signal_key] = value
        
        return signals

    def _are_signals_valid(self, signals):
        """
        Verifies that minimum signals are present.
        Didit recommends at least device_id and app_version.
        """
        required = ['device_id', 'app_version']
        for field in required:
            if field not in signals or not signals[field]:
                return False
        return True

    def _get_missing_signal_fields(self, signals):
        """Returns the list of missing signal fields."""
        required = ['device_id', 'app_version']
        return [f for f in required if not signals.get(f)]

    def _friendly_message(self, status, reason):
        """Translates technical messages from Didit to user-friendly messages."""
        messages = {
            "Blocked": "This number is temporarily blocked",
            "Invalid": "Invalid phone number",
            "Undeliverable": "Unable to send SMS to this number",
            "TooManyAttempts": "Too many attempts, please try again later",
            "CarrierFailure": "Problem with the phone carrier",
            "Unsupported": "Unsupported number",
        }
        
        # Try by reason first, then by status
        if reason in messages:
            return messages[reason]
        elif status in messages:
            return messages[status]
        else:
            return f"Failed to send code ({reason or status})"

    def _extract_phone_details(self, phone_details):
        """
        Extracts and formats phone number details.
        """
        if not phone_details:
            return {"status": "Unknown", "message": "No phone details available"}
            
        return {
            "status": phone_details.get("status"),
            "phone_number_prefix": phone_details.get("phone_number_prefix"),
            "full_number": phone_details.get("full_number"),
            "country_code": phone_details.get("country_code"),
            "country_name": phone_details.get("country_name"),
            "carrier": phone_details.get("carrier"),
            "is_disposable": phone_details.get("is_disposable", False),
            "is_virtual": phone_details.get("is_virtual", False),
            "verification_method": phone_details.get("verification_method"),
            "warnings": phone_details.get("warnings", []),
            "recommendation": phone_details.get("recommendation"),
            "risk_score": phone_details.get("risk_score"),
        }


# Singleton instance
didit_service = DiditVerificationService()