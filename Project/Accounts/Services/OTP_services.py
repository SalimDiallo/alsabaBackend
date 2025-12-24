import requests
import logging
from django.conf import settings
from django.core.cache import cache
from datetime import datetime, timedelta
import uuid

logger = logging.getLogger(__name__)

class DiditVerificationService:
    """
    Service professionnel pour l'API Didit V2
    Documentation: https://docs.didit.me/reference/send-phone-verification-code-api
    """
    
    # URLs d'API CORRIGÉES selon la documentation
    BASE_URL = "https://verification.didit.me/v2"
    SEND_CODE_URL = f"{BASE_URL}/phone/send/"
    VERIFY_CODE_URL = f"{BASE_URL}/phone/verify/"  # À confirmer dans la doc
    
    def __init__(self):
        self.api_key = settings.DIDIT_API_KEY
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Bearer {self.api_key}",  # Format d'authorization
        }
    
    def send_verification_code(self, phone_number, request_meta=None, vendor_data=None):
        """
        Envoie un code de vérification via l'API Didit V2
        
        Args:
            phone_number (str): Numéro au format E.164
            request_meta (dict): Métadonnées de la requête (ip, user_agent, etc.)
            vendor_data (str): Données vendeur optionnelles
        
        Returns:
            dict: {
                "success": bool,
                "request_id": str,  # ID de la requête Didit
                "status": str,      # "Success", "Blocked", etc.
                "reason": str,      # Raison si échec
                "message": str      # Message utilisateur
            }
        """
        payload = {
            "phone_number": phone_number,
            "options": {
                "code_size": 6,
                "locale": "fr-FR",
                "preferred_channel": "sms"  # Par défaut SMS
            }
        }
        
        # Ajouter les signaux de fraude si disponibles
        if request_meta:
            payload["signals"] = self._extract_signals(request_meta)
        
        if vendor_data:
            payload["vendor_data"] = vendor_data
        
        try:
            logger.info(f"Envoi de code Didit à {phone_number}")
            response = requests.post(
                self.SEND_CODE_URL,
                json=payload,
                headers=self.headers,
                timeout=15
            )
            
            response_data = response.json()
            
            # Log détaillé pour le debug
            logger.debug(f"Didit Response - Status: {response.status_code}, Body: {response_data}")
            
            if response.status_code == 200:
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
                    return {
                        "success": False,
                        "request_id": request_id,
                        "status": status,
                        "reason": reason,
                        "message": self._get_user_friendly_message(status, reason)
                    }
            
            elif response.status_code == 401:
                logger.error("Didit API: Clé API invalide")
                return {
                    "success": False,
                    "request_id": None,
                    "status": "Unauthorized",
                    "reason": "invalid_api_key",
                    "message": "Erreur de configuration du service"
                }
            
            elif response.status_code == 403:
                error_detail = response_data.get("detail", response_data.get("error", ""))
                logger.error(f"Didit API: Permission denied - {error_detail}")
                return {
                    "success": False,
                    "request_id": None,
                    "status": "Forbidden",
                    "reason": "permission_denied",
                    "message": "Service temporairement indisponible"
                }
            
            elif response.status_code == 429:
                logger.error("Didit API: Rate limit ou crédits insuffisants")
                return {
                    "success": False,
                    "request_id": None,
                    "status": "TooManyRequests",
                    "reason": "insufficient_credits",
                    "message": "Service temporairement saturé"
                }
            
            else:
                logger.error(f"Didit API: Erreur inattendue - {response.status_code}")
                return {
                    "success": False,
                    "request_id": None,
                    "status": "Error",
                    "reason": f"http_{response.status_code}",
                    "message": "Erreur technique, veuillez réessayer"
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Didit API Request Exception: {str(e)}")
            return {
                "success": False,
                "request_id": None,
                "status": "NetworkError",
                "reason": "request_failed",
                "message": "Service de vérification temporairement indisponible"
            }
        except ValueError as e:
            logger.error(f"Didit API JSON Parse Error: {str(e)}")
            return {
                "success": False,
                "request_id": None,
                "status": "ParseError",
                "reason": "invalid_response",
                "message": "Erreur technique, veuillez réessayer"
            }
    
    def verify_code(self, request_id, code):
        """
        Vérifie un code de vérification
        NOTE: L'endpoint exact doit être confirmé dans la documentation Didit
        """
        # À ADAPTER selon la documentation réelle de vérification
        # Ceci est une implémentation hypothétique
        
        payload = {
            "request_id": request_id,
            "code": code
        }
        
        try:
            response = requests.post(
                self.VERIFY_CODE_URL,
                json=payload,
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                verified = data.get("verified", False)
                
                return {
                    "success": True,
                    "verified": verified,
                    "message": "Code vérifié" if verified else "Code invalide",
                    "details": data
                }
            else:
                return {
                    "success": False,
                    "verified": False,
                    "message": "Échec de vérification",
                    "details": response.json()
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Didit Verify Exception: {str(e)}")
            return {
                "success": False,
                "verified": False,
                "message": "Erreur lors de la vérification"
            }
    
    def _extract_signals(self, request_meta):
        """Extrait les signaux de fraude de la requête"""
        signals = {}
        
        mapping = {
            "ip": "REMOTE_ADDR",
            "user_agent": "HTTP_USER_AGENT",
            "device_id": "HTTP_X_DEVICE_ID",  # Header personnalisé
            "app_version": "HTTP_X_APP_VERSION",
        }
        
        for signal_key, meta_key in mapping.items():
            if meta_key in request_meta:
                signals[signal_key] = request_meta[meta_key]
        
        return signals if signals else None
    
    def _get_user_friendly_message(self, status, reason):
        """Convertit les status/reason Didit en messages utilisateur"""
        messages = {
            "Blocked": {
                "spam": "Ce numéro a été bloqué pour spam",
                "fraud": "Numéro suspect détecté",
                "default": "Numéro temporairement bloqué"
            },
            "Invalid": {
                "default": "Numéro de téléphone invalide"
            },
            "Undeliverable": {
                "default": "Impossible d'envoyer au numéro fourni"
            }
        }
        
        if status in messages and reason in messages[status]:
            return messages[status][reason]
        elif status in messages:
            return messages[status]["default"]
        else:
            return "Échec d'envoi du code de vérification"


# Instance globale du service
didit_service = DiditVerificationService()