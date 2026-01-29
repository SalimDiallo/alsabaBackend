import hashlib
import hmac
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
import structlog

from Accounts.Services.didit_webhook_service import didit_webhook_service

logger = structlog.get_logger(__name__)


class DiditWebhookView(APIView):
    """
    POST /api/webhooks/didit/kyc/
    Webhook pour recevoir les notifications asynchrones de Didit (KYC)
    """
    permission_classes = []  # Pas d'authentification par token, car c'est un webhook externe

    def post(self, request):
        """
        Traite les webhooks Didit pour les mises à jour KYC avec vérification de signature
        """
        try:
            # 1. Vérification de la signature (Sécurité Critique)
            signature = request.META.get('HTTP_X_DIDIT_SIGNATURE')
            webhook_secret = getattr(settings, 'DIDIT_WEBHOOK_SECRET', None)
            
            if webhook_secret:
                if not signature:
                    logger.warning("didit_webhook_signature_missing")
                    return Response({"error": "Signature missing"}, status=status.HTTP_401_UNAUTHORIZED)
                
                # Vérification HMAC-SHA256
                computed_hash = hmac.new(
                    webhook_secret.encode('utf-8'),
                    request.body,
                    hashlib.sha256
                ).hexdigest()
                
                if not hmac.compare_digest(computed_hash, signature):
                    logger.warning("didit_webhook_signature_invalid", received=signature[:10])
                    return Response({"error": "Invalid signature"}, status=status.HTTP_401_UNAUTHORIZED)
            
            webhook_data = request.data
            
            logger.info(
                "didit_webhook_received",
                request_id=webhook_data.get("request_id"),
                status=webhook_data.get("status")
            )

            result = didit_webhook_service.process_kyc_webhook(webhook_data)

            if result["success"]:
                return Response(
                    {"status": "success", "message": result.get("message")},
                    status=status.HTTP_200_OK
                )
            else:
                return Response(
                    {"status": "error", "message": result.get("error")},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            logger.error("didit_webhook_processing_error", error=str(e))
            return Response(
                {"status": "error", "message": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
