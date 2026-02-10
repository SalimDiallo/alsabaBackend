import structlog
import hmac
import hashlib
from django.conf import settings
from django.utils import timezone
from Accounts.models import User

logger = structlog.get_logger(__name__)


class DiditWebhookService:
    """
    Service to process Didit asynchronous webhooks (KYC)
    Documentation: https://docs.didit.me/reference/webhooks
    """

    @staticmethod
    def verify_webhook_signature(payload: str, signature: str) -> bool:
        """
        Verifies the HMAC signature of a DIDIT webhook.
        
        Args:
            payload: Request body (JSON string)
            signature: Signature received in the header
            
        Returns:
            bool: True if valid
        """
        secret = getattr(settings, 'DIDIT_WEBHOOK_SECRET', None)
        if not secret:
            logger.error("didit_webhook_secret_missing")
            return False
            
        try:
            expected_signature = hmac.new(
                secret.encode('utf-8'),
                payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(expected_signature, signature)
        except Exception as e:
            logger.error("didit_signature_verification_error", error=str(e))
            return False

    @staticmethod
    def process_kyc_webhook(webhook_data):
        """
        Processes a Didit KYC verification webhook.

        Args:
            webhook_data: Didit webhook data

        Returns:
            dict: Processing result
        """
        # Didit webhooks (v3) use session_id or request_id as identifies
        session_id = webhook_data.get("session_id")
        request_id = webhook_data.get("request_id")
        vendor_data = webhook_data.get("vendor_data")
        
        # Decide which status to use
        status = webhook_data.get("status")
        decision = webhook_data.get("decision", {})
        
        if decision and not status:
            status = decision.get("status")
            if not vendor_data:
                vendor_data = decision.get("vendor_data")
            
        id_verification = webhook_data.get("id_verification")
        if not id_verification and decision:
            id_verification = decision.get("id_verification", {})
        
        # Identifier for logs
        lookup_id = session_id or request_id or "unknown"

        try:
            # 1. Primary lookup by kyc_request_id (supports session_id or request_id)
            user = None
            if session_id:
                user = User.objects.filter(kyc_request_id=session_id).first()
            
            if not user and request_id:
                user = User.objects.filter(kyc_request_id=request_id).first()
                
            # 2. Fallback lookup by kyc_vendor_data sur le User
            if not user and vendor_data:
                logger.info("didit_webhook_trying_user_vendor_lookup", vendor_data=vendor_data)
                user = User.objects.filter(kyc_vendor_data=vendor_data).first()
                
            # 3. Recherche ultime via KYCDocument (le plus sûr)
            if not user and vendor_data:
                logger.info("didit_webhook_trying_document_lookup", vendor_data=vendor_data)
                from Accounts.models import KYCDocument
                doc = KYCDocument.objects.filter(vendor_data=vendor_data).select_related('user').first()
                if doc:
                    user = doc.user

            if not user:
                logger.warning(
                    "didit_webhook_user_not_found",
                    request_id=lookup_id,
                    session_id=session_id,
                    vendor_data=vendor_data
                )
                return {
                    "success": False,
                    "error": f"User not found for ID: {lookup_id} or Vendor: {vendor_data}"
                }
            
            # Update KYC status according to Didit response
            previous_status = user.kyc_status
            
            if status == "Approved":
                user.kyc_status = "verified"
                user.kyc_verified_at = timezone.now()
                
                # Extract identity data if available
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
                    "message": "KYC approved",
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
                    "message": "KYC rejected",
                    "user_id": str(user.id)
                }
                
            elif status == "Pending":
                # Remains pending (manual review in progress)
                user.kyc_status = "pending"
                user.save()
                
                logger.info(
                    "didit_kyc_pending_via_webhook",
                    user_id=str(user.id),
                    request_id=lookup_id
                )
                
                return {
                    "success": True,
                    "message": "KYC pending review",
                    "user_id": str(user.id)
                }
            else:
                logger.warning(
                    "didit_webhook_unknown_status",
                    status=status,
                    request_id=lookup_id
                )
                return {
                    "success": False,
                    "error": f"Unknown status: {status}"
                }

        except User.DoesNotExist:
            logger.warning(
                "didit_webhook_user_not_found",
                request_id=lookup_id
            )
            return {
                "success": False,
                "error": f"User not found for ID: {lookup_id}"
            }
        except Exception as e:
            logger.error(
                "didit_webhook_processing_error",
                error=str(e),
                request_id=lookup_id
            )
            return {
                "success": False,
                "error": f"Processing error: {str(e)}"
            }


# Singleton instance
didit_webhook_service = DiditWebhookService()
