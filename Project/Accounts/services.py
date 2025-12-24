# your_app/services/kyc_service.py
import requests
from .models import KYCDocument
import random
import string
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import get_user_model
import logging
# Mapping des types de documents vers les IDs de workflow Didit
WORKFLOW_MAPPING = {
    'passport': 'wf_passport_123',          # Remplacez par les vrais IDs
    'id_card': 'wf_id_card_456',
    'drivers_license': 'wf_drivers_license_789',
    # Ajoutez d'autres types
}

class KYCService:
    @staticmethod
    def create_didit_session(document_type: str, user) -> dict:
        """
        Crée une session Didit et retourne les infos (session_id, session_url)
        """
        workflow_id = WORKFLOW_MAPPING.get(document_type)
        if not workflow_id:
            raise ValueError(f"Type de document non supporté: {document_type}")

        payload = {
            "workflow_id": workflow_id,
            "user_reference": str(user.id),
            "redirect_uri": settings.DIDIT_REDIRECT_URI,
            "language": "fr",  # Optionnel
        }

        try:
            response = requests.post(
                f"{settings.DIDIT_API_URL}/sessions",
                headers={
                    "Authorization": f"Bearer {settings.DIDIT_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            return {
                "session_id": data["session_id"],
                "session_url": data["session_url"],
            }
        except requests.RequestException as e:
            raise Exception(f"Erreur Didit API: {str(e)}")

    @staticmethod
    def create_document(user, document_type: str, session_id: str) -> KYCDocument:
        """Crée un KYCDocument local"""
        return KYCDocument.objects.create(
            user=user,
            document_type=document_type,
            session_id=session_id,
            verified=False,
        )

    @staticmethod
    def update_user_status(user, status: str):
        """Met à jour le statut KYC de l'utilisateur"""
        user.kyc_status = status
        if status == 'pending':
            user.kyc_submitted_at = timezone.now()
        elif status == 'verified':
            user.kyc_verified_at = timezone.now()
            user.is_verified = True
        user.save()

    @staticmethod
    def handle_didit_webhook(payload: dict):
        """Traite le webhook Didit"""
        session_id = payload.get("session_id")
        result = payload.get("result")  # 'approved', 'rejected', etc.

        document = KYCDocument.objects.filter(session_id=session_id).first()
        if not document:
            return {"error": "Session non trouvée"}, 404

        user = document.user

        if result == "approved":
            document.verified = True
            document.save()
            KYCService.update_user_status(user, "verified")
            return {"message": "KYC approuvé"}, 200
        elif result == "rejected":
            document.verified = False
            document.save()
            KYCService.update_user_status(user, "rejected")
            return {"message": "KYC rejeté"}, 200
        else:
            return {"error": "Statut inconnu"}, 400
        
logger = logging.getLogger(__name__)
class DiditPhoneService:
    """Service pour l'envoi ET validation via l'API Didit"""
    
    def send_verification_code(self, phone_number, vendor_user_id=None):
        """
        Didit génère et envoie le code automatiquement
        """
        url = "https://api.didit.me/v1/phone/verification/send"
        
        headers = {
            "didit-api-key": settings.DIDIT_API_KEY,
            "Content-Type": "application/json"
        }
        
        payload = {
            "phone": phone_number,
            "options": {
                "code_size": 6,  # Didit générera un code à 6 chiffres
                "locale": "fr-FR",
                "preferred_channel": "sms"  # Optionnel
            }
        }
        
        if vendor_user_id:
            payload["vendor_user_id"] = vendor_user_id
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") == "Success":
                # Didit a envoyé le code, on récupère le session_uuid
                return {
                    "success": True,
                    "message": "Code envoyé avec succès",
                    "session_uuid": data.get("uuid"),
                    # Note: Nous n'avons PAS le code, Didit le garde
                }
            else:
                return {
                    "success": False,
                    "message": f"Échec: {data.get('reason', 'Raison inconnue')}",
                    "session_uuid": None
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur API Didit: {str(e)}")
            return {
                "success": False,
                "message": "Service temporairement indisponible",
                "session_uuid": None
            }
    
    def verify_code(self, session_uuid, user_code):
        """
        Vérifie le code avec Didit
        À implémenter selon la documentation de vérification de Didit
        """
        # EXEMPLE - À adapter selon l'endpoint exact de Didit
        url = "https://api.didit.me/v1/phone/verification/verify"
        
        headers = {
            "didit-api-key": settings.DIDIT_API_KEY,
            "Content-Type": "application/json"
        }
        
        payload = {
            "session_uuid": session_uuid,
            "code": user_code
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            return data.get("verified", False), data.get("message", "")
            
        except requests.exceptions.RequestException:
            return False, "Erreur de vérification"