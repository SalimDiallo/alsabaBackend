# apps/auth/Services/OTP_services.py

import requests
import structlog
from django.conf import settings
from django.core.cache import cache
import uuid

logger = structlog.get_logger(__name__)


class DiditVerificationService:
    """
    Service d'intégration avec Didit V2
    Documentation : https://docs.didit.me
    """
    BASE_URL = "https://verification.didit.me/v2"
    SEND_CODE_URL = f"{BASE_URL}/phone/send"
    VERIFY_CODE_URL = f"{BASE_URL}/phone/check"
    RESEND_CODE_URL = f"{BASE_URL}/phone/resend"

    def __init__(self):
        self.api_key = settings.DIDIT_API_KEY
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-api-key": self.api_key,
        }
        self.timeout = 15

    def send_verification_code(self, phone_number, request_meta=None, vendor_data=None):
        """
        Envoie un code OTP.
        phone_number doit être en E.164 (ex: +33612345678)
        """
        payload = {
            "phone_number": phone_number,
            "options": {"code_size": 6}
        }

        # Ajout des signaux anti-fraude si disponibles et valides
        if request_meta:
            signals = self._extract_signals(request_meta)
            if self._are_signals_valid(signals):
                payload["signals"] = signals
            else:
                missing = self._get_missing_signal_fields(signals)
                logger.warning(
                    "didit_signals_incomplete",
                    phone_number=self._mask_phone(phone_number),
                    missing_fields=missing
                )

        if vendor_data:
            payload["vendor_data"] = vendor_data

        logger.info(
            "didit_send_code_attempt",
            phone_number=self._mask_phone(phone_number),
            has_signals="signals" in payload
        )

        try:
            response = requests.post(
                self.SEND_CODE_URL,
                json=payload,
                headers=self.headers,
                timeout=self.timeout
            )
            response_data = response.json()

            logger.info(
                "didit_send_code_response",
                status_code=response.status_code,
                status=response_data.get("status"),
                request_id=response_data.get("request_id", "N/A")[:20]
            )

            if response.status_code == 200:
                return self._handle_success_send(response_data)
            else:
                return self._handle_error_send(response.status_code, response_data)

        except requests.exceptions.Timeout:
            logger.error("didit_send_timeout", phone_number=self._mask_phone(phone_number))
            return self._error_response("Timeout", "request_timeout", "Service trop lent")
        except requests.exceptions.RequestException as e:
            logger.error("didit_send_network_error", error=str(e))
            return self._error_response("NetworkError", "request_failed", "Service indisponible")
        except ValueError:
            logger.error("didit_send_json_error")
            return self._error_response("ParseError", "invalid_response", "Réponse invalide")

    def verify_code(self, phone_number, code):
        """
        Vérifie le code OTP avec Didit.
        phone_number en E.164
        """
        payload = {
            "phone_number": phone_number,
            "code": code,
            "duplicate_phone_action": "NO_ACTION",
            "disposable_phone_action": "NO_ACTION",
            "voip_phone_action": "NO_ACTION"
        }

        logger.info(
            "didit_verify_attempt",
            phone_number=self._mask_phone(phone_number),
            code_length=len(code)
        )

        try:
            response = requests.post(
                self.VERIFY_CODE_URL,
                json=payload,
                headers=self.headers,
                timeout=10
            )
            response_data = response.json()

            logger.info(
                "didit_verify_response",
                status_code=response.status_code,
                phone_status=response_data.get("phone", {}).get("status")
            )

            if response.status_code != 200:
                return {
                    "success": False,
                    "verified": False,
                    "status": "http_error",
                    "message": "Erreur service Didit",
                    "details": response_data
                }

            phone_details = response_data.get("phone", {})
            status = phone_details.get("status", "Unknown")
            verified = (status == "Approved")

            return {
                "success": True,
                "verified": verified,
                "status": status,
                "message": response_data.get("message", "Vérification traitée"),
                "phone_details": {
                    "status": phone_details.get("status"),
                    "phone_number_prefix": phone_details.get("phone_number_prefix"),
                    "full_number": phone_details.get("full_number"),
                    "country_code": phone_details.get("country_code"),
                    "country_name": phone_details.get("country_name"),
                    "carrier": phone_details.get("carrier"),
                    "is_disposable": phone_details.get("is_disposable", False),
                    "is_virtual": phone_details.get("is_virtual", False),
                    "verification_method": phone_details.get("verification_method"),
                    "warnings": phone_details.get("warnings", [])
                }
            }

        except requests.exceptions.RequestException as e:
            logger.error("didit_verify_network_error", error=str(e))
            return {"success": False, "verified": False, "message": "Erreur réseau"}
        except ValueError:
            logger.error("didit_verify_json_error")
            return {"success": False, "verified": False, "message": "Réponse invalide"}

    def resend_code(self, request_id):
        payload = {"request_id": request_id}

        try:
            response = requests.post(
                self.RESEND_CODE_URL,
                json=payload,
                headers=self.headers,
                timeout=self.timeout
            )
            response_data = response.json()

            if response.status_code == 200:
                return {
                    "success": True,
                    "request_id": response_data.get("request_id", request_id),
                    "message": "Code renvoyé avec succès"
                }
            else:
                logger.warning("didit_resend_failed", status=response.status_code)
                return {"success": False, "message": "Échec renvoi"}

        except requests.exceptions.RequestException as e:
            logger.error("didit_resend_error", error=str(e))
            return {"success": False, "message": "Erreur réseau"}

    # === Méthodes utilitaires ===

    def _handle_success_send(self, data):
        status = data.get("status")
        if status == "Success":
            return {
                "success": True,
                "request_id": data.get("request_id"),
                "status": status,
                "message": "Code envoyé avec succès"
            }
        else:
            reason = data.get("reason", "unknown")
            return {
                "success": False,
                "request_id": data.get("request_id"),
                "status": status,
                "reason": reason,
                "message": self._friendly_message(status, reason)
            }

    def _handle_error_send(self, status_code, data):
        if status_code == 400:
            msg = data.get("detail") or data.get("message") or "Requête invalide"
            return self._error_response("BadRequest", "invalid_request", msg)
        elif status_code == 401:
            return self._error_response("Unauthorized", "invalid_key", "Clé API invalide")
        elif status_code == 403:
            return self._error_response("Forbidden", "permission_denied", "Accès refusé")
        elif status_code == 429:
            return self._error_response("RateLimited", "rate_limited", "Trop de requêtes")
        else:
            return self._error_response("ServerError", "unexpected", "Erreur technique")

    def _error_response(self, status, reason, message):
        return {
            "success": False,
            "status": status,
            "reason": reason,
            "message": message
        }

    def _extract_signals(self, request_meta):
        signals = {}
        mapping = {
            'ip': 'REMOTE_ADDR',
            'user_agent': 'HTTP_USER_AGENT',
            'device_id': 'HTTP_X_DEVICE_ID',
            'app_version': 'HTTP_X_APP_VERSION',
        }

        for key, meta_key in mapping.items():
            value = request_meta.get(meta_key, '').strip()
            if not value:
                if key == 'device_id':
                    value = f"web_{uuid.uuid4().hex[:8]}"
                elif key == 'app_version':
                    value = "1.0.0"
                elif key == 'ip':
                    value = "0.0.0.0"
                elif key == 'user_agent':
                    value = "Unknown"

            if value:
                signals[key] = value

        return signals

    def _are_signals_valid(self, signals):
        required = ['device_id', 'app_version']
        for field in required:
            if field not in signals or not signals[field]:
                return False
        return True

    def _get_missing_signal_fields(self, signals):
        required = ['device_id', 'app_version']
        return [f for f in required if not signals.get(f)]

    def _friendly_message(self, status, reason):
        messages = {
            "Blocked": "Numéro temporairement bloqué",
            "Invalid": "Numéro invalide ou non supporté",
            "Undeliverable": "Impossible d'envoyer le SMS",
            "TooManyAttempts": "Trop de tentatives, réessayez plus tard"
        }
        return messages.get(status, f"Échec envoi ({reason})")

    def _mask_phone(self, phone_number):
        if len(phone_number or "") > 10:
            return phone_number[:6] + "****" + phone_number[-2:]
        return "****"


# Instance unique
didit_service = DiditVerificationService()