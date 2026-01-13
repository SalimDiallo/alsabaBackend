# apps/auth/Services/OTP_services.py
import requests
import structlog
from django.conf import settings
from ..utils import auth_utils
import uuid

logger = structlog.get_logger(__name__)


class DiditVerificationService:
    """
    Service d'intégration avec Didit V2 - Version adaptée sans resend
    Documentation : https://docs.didit.me
    Note: Didit ne propose pas d'endpoint resend, on doit renvoyer un nouveau code
    """
    BASE_URL = "https://verification.didit.me/v2"
    SEND_CODE_URL = f"{BASE_URL}/phone/send"
    VERIFY_CODE_URL = f"{BASE_URL}/phone/check"
    # PAS de RESEND_CODE_URL - Didit ne propose pas cette fonctionnalité

    def __init__(self):
        if not settings.DIDIT_API_KEY:
            raise ValueError("DIDIT_API_KEY n'est pas configurée dans settings")
        
        self.api_key = settings.DIDIT_API_KEY
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-api-key": self.api_key,
        }
        self.timeout = 15

    def send_verification_code(self, phone_number, request_meta=None, vendor_data=None):
        """
        Envoie un code OTP via Didit.
        
        Args:
            phone_number: Format E.164 (ex: +33612345678)
            request_meta: Métadonnées de la requête
            vendor_data: Identifiant interne pour corrélation
        
        Returns:
            dict: Résultat de l'envoi avec request_id
        """
        # Validation du format E.164
        if not auth_utils.validate_e164_format(phone_number):
            logger.error("invalid_e164_format", phone_number=auth_utils.mask_phone(phone_number))
            return self._error_response(
                "InvalidFormat", 
                "invalid_phone_format", 
                "Format de numéro invalide"
            )
        
        payload = {
            "phone_number": phone_number,
            "options": {
                "code_size": 6,
                "locale": "fr-FR",
                "preferred_channel": "sms"
            }
        }

        # Ajout des signaux anti-fraude
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
                "Le service est temporairement indisponible"
            )
        except requests.exceptions.RequestException as e:
            logger.error("didit_send_network_error", error=str(e))
            return self._error_response(
                "NetworkError", 
                "service_unavailable", 
                "Service temporairement indisponible"
            )
        except ValueError as e:
            logger.error("didit_send_json_error", error=str(e))
            return self._error_response(
                "ParseError", 
                "invalid_response", 
                "Réponse invalide du service"
            )

    def verify_code(self, phone_number, code, request_id=None):
        """
        Vérifie un code OTP avec Didit.
        
        Args:
            phone_number: Format E.164
            code: Code OTP (6 chiffres)
            request_id: Optionnel - ID de la requête Didit pour tracking
        
        Returns:
            dict: Résultat de la vérification avec détails
        """
        # Validation des entrées
        if not auth_utils.validate_e164_format(phone_number):
            return {
                "success": False,
                "verified": False,
                "message": "Format de numéro invalide",
                "code": "invalid_phone_format"
            }
        
        if not code or not code.isdigit() or len(code) != 6:
            return {
                "success": False,
                "verified": False,
                "message": "Code OTP invalide (6 chiffres requis)",
                "code": "invalid_otp_format"
            }

        payload = {
            "phone_number": phone_number,
            "code": code,
        }

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
                phone_number=auth_utils.mask_phone(phone_number)
            )
            
            response_data = response.json() if response.content else {}

            if response.status_code != 200:
                return self._handle_verification_error(response.status_code, response_data)

            phone_details = response_data.get("phone", {})
            status = phone_details.get("status", "Unknown")
            verified = (status == "Approved")

            return {
                "success": True,
                "verified": verified,
                "status": status,
                "message": response_data.get("message", "Vérification effectuée"),
                "phone_details": self._extract_phone_details(phone_details)
            }

        except requests.exceptions.Timeout:
            logger.error("didit_verify_timeout", phone_number=auth_utils.mask_phone(phone_number))
            return {"success": False, "verified": False, "message": "Timeout de vérification"}
        except requests.exceptions.RequestException as e:
            logger.error("didit_verify_network_error", error=str(e))
            return {"success": False, "verified": False, "message": "Erreur réseau"}
        except ValueError as e:
            logger.error("didit_verify_json_error", error=str(e))
            return {"success": False, "verified": False, "message": "Réponse invalide"}

    # === Méthodes utilitaires privées ===

    def _handle_success_send(self, data):
        """Traite une réponse réussie d'envoi de code."""
        status = data.get("status")
        request_id = data.get("request_id")
        
        if status == "Success":
            return {
                "success": True,
                "request_id": request_id,
                "status": status,
                "message": "Code de vérification envoyé par SMS"
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
        """Traite les erreurs HTTP lors de l'envoi."""
        error_messages = {
            400: ("BadRequest", "invalid_request", "Requête invalide vers Didit"),
            401: ("Unauthorized", "invalid_key", "Clé API Didit invalide"),
            403: ("Forbidden", "permission_denied", "Accès refusé à l'API Didit"),
            429: ("RateLimited", "rate_limited", "Trop de requêtes vers Didit"),
            500: ("ServerError", "didit_server_error", "Erreur interne chez Didit"),
            502: ("BadGateway", "bad_gateway", "Problème de connexion à Didit"),
            503: ("ServiceUnavailable", "service_unavailable", "Didit temporairement indisponible"),
        }
        
        if status_code in error_messages:
            status, reason, default_message = error_messages[status_code]
            message = data.get("detail") or data.get("message") or default_message
            return self._error_response(status, reason, message)
        else:
            message = data.get("detail") or data.get("message") or f"Erreur Didit ({status_code})"
            return self._error_response("HttpError", "http_error", message)

    def _handle_verification_error(self, status_code, data):
        """Traite les erreurs HTTP lors de la vérification."""
        if status_code == 400:
            return {
                "success": False,
                "verified": False,
                "message": data.get("detail", "Requête de vérification invalide"),
                "code": "verification_failed"
            }
        elif status_code == 429:
            return {
                "success": False,
                "verified": False,
                "message": "Trop de tentatives de vérification",
                "code": "verification_rate_limited",
                "retry_after": 60
            }
        else:
            return {
                "success": False,
                "verified": False,
                "message": f"Erreur lors de la vérification ({status_code})",
                "code": "verification_error"
            }

    def _error_response(self, status, reason, message):
        """Format standard pour les réponses d'erreur."""
        return {
            "success": False,
            "status": status,
            "reason": reason,
            "message": message
        }

    def _extract_signals(self, request_meta):
        """
        Extrait les signaux anti-fraude des métadonnées de requête.
        Format attendu par Didit: https://docs.didit.me/reference/phone-verification-signals
        """
        signals = {}
        
        # Mapping des champs
        mapping = {
            'device_id': 'device_id',
            'app_version': 'app_version',
            'ip': 'client_ip',
            'user_agent': 'user_agent',
        }
        
        for signal_key, meta_key in mapping.items():
            value = request_meta.get(meta_key, '').strip()
            
            # Valeurs par défaut intelligentes
            if not value:
                if signal_key == 'device_id':
                    value = f"web_{uuid.uuid4().hex[:8]}"
                elif signal_key == 'app_version':
                    value = "1.0.0"
                elif signal_key == 'ip':
                    # Ne jamais mettre 0.0.0.0, utiliser l'IP réelle ou 'unknown'
                    value = request_meta.get('client_ip', 'unknown')[:50]
                elif signal_key == 'user_agent':
                    value = "Unknown"
            
            if value:
                signals[signal_key] = value
        
        return signals

    def _are_signals_valid(self, signals):
        """
        Vérifie que les signaux minimums sont présents.
        Didit recommande au moins device_id et app_version.
        """
        required = ['device_id', 'app_version']
        for field in required:
            if field not in signals or not signals[field]:
                return False
        return True

    def _get_missing_signal_fields(self, signals):
        """Retourne la liste des champs de signal manquants."""
        required = ['device_id', 'app_version']
        return [f for f in required if not signals.get(f)]

    def _friendly_message(self, status, reason):
        """Traduit les messages techniques de Didit en messages utilisateur."""
        messages = {
            "Blocked": "Ce numéro est temporairement bloqué",
            "Invalid": "Numéro de téléphone invalide",
            "Undeliverable": "Impossible d'envoyer le SMS à ce numéro",
            "TooManyAttempts": "Trop de tentatives, veuillez réessayer plus tard",
            "CarrierFailure": "Problème avec l'opérateur téléphonique",
            "Unsupported": "Numéro non supporté",
        }
        
        # Essayer d'abord par raison, puis par status
        if reason in messages:
            return messages[reason]
        elif status in messages:
            return messages[status]
        else:
            return f"Échec d'envoi du code ({reason or status})"

    def _extract_phone_details(self, phone_details):
        """
        Extrait et formate les détails du numéro de téléphone.
        """
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


# Instance singleton
didit_service = DiditVerificationService()