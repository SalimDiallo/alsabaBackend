import requests
import logging
import structlog
from django.conf import settings
from django.core.cache import cache
from datetime import datetime
import uuid

# Logs structurés
logger = structlog.get_logger(__name__)

class DiditVerificationService:
    """
    Service professionnel pour l'API Didit V2
    Documentation: https://docs.didit.me
    """
    
    BASE_URL = "https://verification.didit.me/v2"
    SEND_CODE_URL = f"{BASE_URL}/phone/send"
    VERIFY_CODE_URL = f"{BASE_URL}/phone/check"
    RESEND_CODE_URL = f"{BASE_URL}/phone/resend"  # À vérifier selon la doc
    
    def __init__(self):
        self.api_key = settings.DIDIT_API_KEY
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-api-key": f"{self.api_key}",
        }
        self.timeout = 15
    
    def send_verification_code(self, phone_number, request_meta=None, vendor_data=None):
        """
        Envoie un code de vérification via l'API Didit V2
        """
        # Payload de base
        payload = {
            "phone_number": phone_number,
        }
        
        # Options - version simplifiée
        payload["options"] = {
            "code_size": 6
        }
        
        # Signaux de fraude - N'envoyer QUE si tous les champs sont valides
        if request_meta:
            signals = self._extract_signals(request_meta)
            # Vérifier que les signaux sont complets avant de les envoyer
            if self._are_signals_valid(signals):
                payload["signals"] = signals
            else:
                logger.warning(
                    "didit_signals_incomplete",
                    missing_fields=self._get_missing_signal_fields(signals),
                    message="Signals non envoyés (champs manquants ou invalides)"
                )
        
        if vendor_data:
            payload["vendor_data"] = vendor_data
        
        # Log avant envoi
        logger.info(
            "didit_send_code_attempt",
            phone_number=self._mask_phone(phone_number),
            has_signals='signals' in payload,
            payload_keys=list(payload.keys())
        )
        
        try:
            response = requests.post(
                self.SEND_CODE_URL,
                json=payload,
                headers=self.headers,
                timeout=self.timeout
            )
            
            response_data = response.json()
            
            # Log réponse
            logger.info(
                "didit_send_code_response",
                status_code=response.status_code,
                didit_status=response_data.get("status"),
                request_id=response_data.get("request_id", "N/A")[:20]
            )
            
            # Traitement selon le statut HTTP
            if response.status_code == 200:
                return self._handle_success_response(response_data)
            elif response.status_code == 400:
                return self._handle_bad_request(response_data, payload)
            elif response.status_code == 401:
                return self._handle_unauthorized()
            elif response.status_code == 403:
                return self._handle_forbidden(response_data)
            elif response.status_code == 429:
                return self._handle_rate_limit()
            else:
                return self._handle_unexpected_error(response.status_code)
                
        except requests.exceptions.Timeout:
            logger.error("didit_api_timeout", timeout=self.timeout)
            return self._create_error_response(
                "Timeout",
                "request_timeout",
                "Le service de vérification est trop lent"
            )
        except requests.exceptions.RequestException as e:
            logger.error("didit_api_request_error", error=str(e))
            return self._create_error_response(
                "NetworkError",
                "request_failed",
                "Service de vérification temporairement indisponible"
            )
        except ValueError as e:
            logger.error("didit_json_parse_error", error=str(e))
            return self._create_error_response(
                "ParseError",
                "invalid_response",
                "Erreur technique dans la réponse du service"
            )
    
    def verify_code(self, phone_number, code):
        """
        Vérifie un code OTP avec Didit selon la doc officielle.
        Utilise 'phone' et 'code', avec actions de risque configurables.
        """
        payload = {
            "phone": phone_number,
            "code": code,
            "duplicate_phone_action": "DECLINE",   # Refuser si numéro déjà utilisé ailleurs
            "disposable_phone_action": "DECLINE",  # Refuser les numéros temporaires
            "voip_phone_action": "DECLINE"         # Refuser les VoIP/virtual numbers
        }
        
        try:
            logger.info(
                "didit_verify_attempt",
                phone_number=self._mask_phone(phone_number),
                code_length=len(code)
            )
            
            response = requests.post(
                self.VERIFY_CODE_URL,  # Doit être "https://verification.didit.me/v2/phone/check/"
                json=payload,
                headers=self.headers,
                timeout=10
            )
            
            response_data = response.json()
            
            logger.info(
                "didit_verify_response",
                status_code=response.status_code,
                phone_status=response_data.get("phone", {}).get("status"),
                message=response_data.get("message")
            )
            
            if response.status_code != 200:
                return {
                    "success": False,
                    "verified": False,
                    "status": "http_error",
                    "message": "Erreur du service Didit",
                    "details": response_data
                }
            
            phone_details = response_data.get("phone", {})
            phone_status = phone_details.get("status", "Unknown")
            verified = (phone_status == "Approved")
            
            return {
                "success": True,
                "verified": verified,
                "status": phone_status,
                "message": response_data.get("message", "Vérification traitée"),
                "request_id": response_data.get("request_id"),  # Peut exister ou non
                "phone_details": {
                    "status": phone_details.get("status"),
                    "phone_number_prefix": phone_details.get("phone_number_prefix"),
                    "phone_number": phone_details.get("phone_number"),
                    "full_number": phone_details.get("full_number"),
                    "country_code": phone_details.get("country_code"),
                    "country_name": phone_details.get("country_name"),
                    "carrier": phone_details.get("carrier"),
                    "is_disposable": phone_details.get("is_disposable", False),
                    "is_virtual": phone_details.get("is_virtual", False),
                    "verification_method": phone_details.get("verification_method"),
                    "verification_attempts": phone_details.get("verification_attempts"),
                    "verified_at": phone_details.get("verified_at"),
                    "lifecycle": phone_details.get("lifecycle"),
                    "warnings": phone_details.get("warnings", [])
                },
                "created_at": response_data.get("created_at"),
                "details": response_data
            }
                    
        except requests.exceptions.RequestException as e:
            logger.error("didit_verify_request_error", error=str(e))
            return {
                "success": False,
                "verified": False,
                "status": "network_error",
                "message": "Erreur réseau lors de la vérification"
            }
        except ValueError as e:
            logger.error("didit_verify_json_error", error=str(e))
            return {
                "success": False,
                "verified": False,
                "status": "parse_error",
                "message": "Erreur dans la réponse du service"
            }
    
    def resend_code(self, request_id):
        """
        Renvoie un code OTP (si supporté par Didit)
        """
        payload = {
            "request_id": request_id
        }
        
        try:
            logger.info("didit_resend_attempt", request_id=request_id[:8] + "...")
            
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
                    "status": "resent",
                    "message": "Code renvoyé avec succès"
                }
            else:
                logger.warning(
                    "didit_resend_failed",
                    status_code=response.status_code,
                    response=response_data
                )
                return {
                    "success": False,
                    "status": "resend_failed",
                    "message": "Échec du renvoi du code",
                    "details": response_data
                }
                
        except requests.exceptions.RequestException as e:
            logger.error("didit_resend_error", error=str(e))
            return {
                "success": False,
                "status": "network_error",
                "message": "Erreur réseau lors du renvoi"
            }
    
    def _handle_success_response(self, response_data):
        """Gère les réponses 200 OK"""
        status = response_data.get("status", "Unknown")
        request_id = response_data.get("request_id")
        
        if status == "Success":
            return {
                "success": True,
                "request_id": request_id,
                "status": status,
                "reason": None,
                "message": "Code de vérification envoyé avec succès"
            }
        else:
            reason = response_data.get("reason", "unknown_reason")
            logger.warning(
                "didit_send_not_success",
                status=status,
                reason=reason,
                request_id=request_id
            )
            return {
                "success": False,
                "request_id": request_id,
                "status": status,
                "reason": reason,
                "message": self._get_user_friendly_message(status, reason)
            }
    
    def _handle_bad_request(self, response_data, payload_sent):
        """Gère les erreurs 400 avec plus de détails"""
        logger.error(
            "didit_bad_request",
            details=response_data,
            payload_sent={
                "phone_number": self._mask_phone(payload_sent.get("phone_number", "")),
                "has_signals": "signals" in payload_sent,
                "signals_keys": list(payload_sent.get("signals", {}).keys()) if "signals" in payload_sent else []
            }
        )
        
        # Essayer d'extraire le message d'erreur spécifique
        error_message = "Requête invalide"
        if isinstance(response_data, dict):
            if "detail" in response_data:
                error_message = response_data["detail"]
            elif "error" in response_data:
                error_message = response_data["error"]
            elif "message" in response_data:
                error_message = response_data["message"]
        
        return self._create_error_response(
            "BadRequest",
            "invalid_request",
            f"Erreur de configuration: {error_message}"
        )
    
    def _handle_unauthorized(self):
        """Gère les erreurs 401"""
        logger.error("didit_unauthorized")
        return self._create_error_response(
            "Unauthorized",
            "invalid_api_key",
            "Clé API invalide ou expirée"
        )
    
    def _handle_forbidden(self, response_data):
        """Gère les erreurs 403"""
        logger.error("didit_forbidden", details=response_data)
        return self._create_error_response(
            "Forbidden",
            "permission_denied",
            "Accès refusé au service de vérification"
        )
    
    def _handle_rate_limit(self):
        """Gère les erreurs 429"""
        logger.error("didit_rate_limit")
        return self._create_error_response(
            "TooManyRequests",
            "rate_limited",
            "Limite de requêtes atteinte, veuillez réessayer plus tard"
        )
    
    def _handle_unexpected_error(self, status_code):
        """Gère les autres erreurs HTTP"""
        logger.error("didit_unexpected_error", status_code=status_code)
        return self._create_error_response(
            f"HTTP_{status_code}",
            "server_error",
            "Erreur technique du service de vérification"
        )
    
    def _create_error_response(self, status, reason, message):
        """Crée une réponse d'erreur standardisée"""
        return {
            "success": False,
            "request_id": None,
            "status": status,
            "reason": reason,
            "message": message
        }
    
    def _extract_signals(self, request_meta):
        """
        Extrait et valide les signaux de fraude
        Retourne un dict avec les signaux ou None si invalide
        """
        signals = {}
        
        # Mapping des headers
        mapping = {
            'ip': 'REMOTE_ADDR',
            'user_agent': 'HTTP_USER_AGENT',
            'device_id': 'HTTP_X_DEVICE_ID',
            'app_version': 'HTTP_X_APP_VERSION',
        }
        
        for signal_key, meta_key in mapping.items():
            value = request_meta.get(meta_key, '')
            
            # Convertir en string si ce n'est pas déjà le cas
            if not isinstance(value, str):
                value = str(value)
            
            # Nettoyer et valider
            value = value.strip()
            
            # Pour device_id et app_version, générer des valeurs par défaut si vide
            if signal_key == 'device_id' and not value:
                value = f"web_{uuid.uuid4().hex[:8]}"
            
            if signal_key == 'app_version' and not value:
                value = "1.0.0"
            
            # Pour ip et user_agent, utiliser des valeurs par défaut si nécessaire
            if signal_key == 'ip' and not value:
                value = "0.0.0.0"
            
            if signal_key == 'user_agent' and not value:
                value = "Unknown/1.0"
            
            # S'assurer que la valeur n'est jamais vide
            if value:
                signals[signal_key] = value
        
        return signals
    
    def _are_signals_valid(self, signals):
        """
        Vérifie que tous les champs requis dans signals sont présents et valides
        Selon l'erreur reçue, Didit exige apparemment device_id et app_version non vides
        """
        if not signals:
            return False
        
        # Champs requis basés sur l'erreur reçue
        required_fields = ['device_id', 'app_version']
        
        for field in required_fields:
            if field not in signals:
                logger.warning(f"didit_missing_required_field", field=field)
                return False
            
            value = signals[field]
            if not value or not isinstance(value, str) or not value.strip():
                logger.warning(f"didit_empty_required_field", field=field, value=value)
                return False
        
        return True
    
    def _get_missing_signal_fields(self, signals):
        """Retourne la liste des champs manquants dans les signaux"""
        required_fields = ['device_id', 'app_version']
        missing = []
        
        for field in required_fields:
            if field not in signals or not signals[field] or not str(signals[field]).strip():
                missing.append(field)
        
        return missing
    
    def _get_user_friendly_message(self, status, reason):
        """Messages utilisateur adaptés"""
        messages = {
            "Blocked": {
                "spam": "Ce numéro a été temporairement bloqué pour cause de spam",
                "fraud": "Activité suspecte détectée, le numéro est bloqué",
                "default": "Numéro temporairement indisponible"
            },
            "Invalid": {
                "invalid_number": "Numéro de téléphone invalide",
                "unsupported_country": "Pays non supporté",
                "default": "Numéro de téléphone invalide"
            },
            "Undeliverable": {
                "default": "Impossible d'atteindre ce numéro"
            },
            "AlreadyVerified": {
                "default": "Ce numéro est déjà vérifié"
            },
            "TooManyAttempts": {
                "default": "Trop de tentatives, veuillez réessayer plus tard"
            }
        }
        
        if status in messages and reason in messages[status]:
            return messages[status][reason]
        elif status in messages:
            return messages[status]["default"]
        else:
            return f"Échec d'envoi du code (raison: {reason})"
    
    def _mask_phone(self, phone_number):
        """Masque partiellement le numéro pour les logs"""
        if not phone_number or not isinstance(phone_number, str):
            return "****"
        
        if len(phone_number) > 6:
            return phone_number[:4] + "****" + phone_number[-2:]
        return "****"


# Instance singleton
didit_service = DiditVerificationService()