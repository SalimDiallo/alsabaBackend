import structlog
from django.utils import timezone
from Accounts.models import User

logger = structlog.get_logger(__name__)


class DiditWebhookService:
    """
    Service pour traiter les webhooks asynchrones de Didit (KYC)
    Documentation: https://docs.didit.me/reference/webhooks
    """

    @staticmethod
    def process_kyc_webhook(webhook_data):
        """
        Traite un webhook de vérification KYC Didit

        Args:
            webhook_data: Données du webhook Didit

        Returns:
            dict: Résultat du traitement
        """
        request_id = webhook_data.get("request_id")
        status = webhook_data.get("status")
        id_verification = webhook_data.get("id_verification", {})
        
        if not request_id:
            logger.warning("didit_webhook_missing_request_id", data=webhook_data)
            return {"success": False, "error": "request_id manquant"}

        try:
            # Trouver l'utilisateur par request_id
            user = User.objects.get(kyc_request_id=request_id)
            
            # Mettre à jour le statut KYC selon la réponse Didit
            previous_status = user.kyc_status
            
            if status == "Approved":
                user.kyc_status = "verified"
                user.kyc_verified_at = timezone.now()
                
                # Extraire les données d'identité si disponibles
                document_data = id_verification.get("document", {})
                if document_data:
                    user.kyc_document_type = document_data.get("type")
                    user.kyc_document_number = document_data.get("document_number")
                    user.kyc_full_name = document_data.get("full_name")
                    user.kyc_date_of_birth = document_data.get("date_of_birth")
                    user.kyc_nationality = document_data.get("nationality")
                    user.kyc_gender = document_data.get("gender")
                    user.kyc_expiration_date = document_data.get("expiration_date")
                
                user.save()
                
                logger.info(
                    "didit_kyc_approved_via_webhook",
                    user_id=str(user.id),
                    request_id=request_id,
                    previous_status=previous_status
                )
                
                return {
                    "success": True,
                    "message": "KYC approuvé",
                    "user_id": str(user.id)
                }
                
            elif status == "Declined":
                user.kyc_status = "rejected"
                user.save()
                
                logger.info(
                    "didit_kyc_rejected_via_webhook",
                    user_id=str(user.id),
                    request_id=request_id,
                    reason=id_verification.get("decline_reason")
                )
                
                return {
                    "success": True,
                    "message": "KYC rejeté",
                    "user_id": str(user.id)
                }
                
            elif status == "Pending":
                # Reste en pending (revue manuelle en cours)
                user.kyc_status = "pending"
                user.save()
                
                logger.info(
                    "didit_kyc_pending_via_webhook",
                    user_id=str(user.id),
                    request_id=request_id
                )
                
                return {
                    "success": True,
                    "message": "KYC en attente de revue",
                    "user_id": str(user.id)
                }
            else:
                logger.warning(
                    "didit_webhook_unknown_status",
                    status=status,
                    request_id=request_id
                )
                return {
                    "success": False,
                    "error": f"Statut inconnu: {status}"
                }

        except User.DoesNotExist:
            logger.warning(
                "didit_webhook_user_not_found",
                request_id=request_id
            )
            return {
                "success": False,
                "error": "Utilisateur non trouvé"
            }
        except Exception as e:
            logger.error(
                "didit_webhook_processing_error",
                error=str(e),
                request_id=request_id
            )
            return {
                "success": False,
                "error": f"Erreur de traitement: {str(e)}"
            }


# Instance singleton
didit_webhook_service = DiditWebhookService()
