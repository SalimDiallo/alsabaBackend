import hashlib
import hmac
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
import structlog
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from Accounts.Services.didit_webhook_service import didit_webhook_service

logger = structlog.get_logger(__name__)


class DiditWebhookView(APIView):
    """
    POST /api/webhooks/didit/kyc/
    Webhook pour recevoir les notifications asynchrones de Didit (KYC)
    """
    permission_classes = []  # Pas d'authentification par token, car c'est un webhook externe

    @extend_schema(
        summary="Webhook Didit KYC",
        description="Reçoit les callbacks de statut de vérification KYC. Nécessite les headers X-Signature et X-Timestamp (v3).",
        parameters=[
            OpenApiParameter("X-Signature", OpenApiTypes.STR, location=OpenApiParameter.HEADER, description="Signature HMAC-SHA256 du payload", required=True),
            OpenApiParameter("X-Timestamp", OpenApiTypes.STR, location=OpenApiParameter.HEADER, description="Timestamp UNIX de la requête", required=True),
        ],
        responses={200: {"description": "Webhook traité avec succès"}},
        request=OpenApiTypes.OBJECT # Payload JSON générique
    )
    def post(self, request):
        """
        Traite les webhooks Didit pour les mises à jour KYC avec vérification de signature
        """
        import time
        from Accounts.models import WebhookAuditLog
        
        start_time = time.time()
        audit_log = None
        
        # Extraire les métadonnées de la requête
        ip_address = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
        if ip_address:
            ip_address = ip_address.split(',')[0].strip()
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        payload_size = len(request.body)
        
        try:
            webhook_data = request.data
            request_id = webhook_data.get("request_id", "unknown")
            didit_status = webhook_data.get("status", "")
            
            # Log initial de réception
            logger.info(
                "didit_webhook_request_received",
                request_id=request_id,
                status=didit_status,
                ip_address=ip_address,
                payload_size=payload_size,
                user_agent=user_agent[:100] if user_agent else None
            )
            
            # 1. Vérification de la signature et du timestamp (Sécurité Critique)
            signature = request.META.get('HTTP_X_SIGNATURE')
            timestamp = request.META.get('HTTP_X_TIMESTAMP')
            webhook_secret = getattr(settings, 'DIDIT_WEBHOOK_SECRET', None)
            
            # Vérification du timestamp (Replay Protection - max 5 min)
            if timestamp:
                try:
                    ts_int = int(timestamp)
                    current_ts = int(time.time())
                    if abs(current_ts - ts_int) > 300:  # 5 minutes
                        logger.warning("didit_webhook_timestamp_too_old", timestamp=timestamp, diff=current_ts - ts_int)
                        return Response({"error": "Request too old"}, status=status.HTTP_401_UNAUTHORIZED)
                except ValueError:
                    pass
            
            if not webhook_secret:
                logger.error("didit_webhook_secret_missing", request_id=request_id)
                # Créer audit log pour erreur de configuration
                WebhookAuditLog.objects.create(
                    request_id=request_id,
                    didit_status=didit_status,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    payload_size=payload_size,
                    signature_valid=False,
                    webhook_status='failed',
                    error_message="Webhook secret not configured",
                    raw_payload=webhook_data
                )
                return Response({"error": "Webhook secret not configured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            if not signature:
                logger.warning("didit_webhook_signature_missing", request_id=request_id, ip_address=ip_address)
                # Créer audit log pour signature manquante
                WebhookAuditLog.objects.create(
                    request_id=request_id,
                    didit_status=didit_status,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    payload_size=payload_size,
                    signature_valid=False,
                    webhook_status='signature_invalid',
                    error_message="Signature missing",
                    raw_payload=webhook_data
                )
                return Response({"error": "Signature missing"}, status=status.HTTP_401_UNAUTHORIZED)
            
            # Vérification HMAC-SHA256
            computed_hash = hmac.new(
                webhook_secret.encode('utf-8'),
                request.body,
                hashlib.sha256
            ).hexdigest()
            
            signature_valid = hmac.compare_digest(computed_hash, signature)
            
            if not signature_valid:
                logger.warning(
                    "didit_webhook_signature_invalid",
                    request_id=request_id,
                    ip_address=ip_address,
                    received_signature=signature[:10]
                )
                # Créer audit log pour signature invalide
                WebhookAuditLog.objects.create(
                    request_id=request_id,
                    didit_status=didit_status,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    payload_size=payload_size,
                    signature_valid=False,
                    signature_received=signature[:20],
                    webhook_status='signature_invalid',
                    error_message="Invalid signature",
                    raw_payload=webhook_data
                )
                return Response({"error": "Invalid signature"}, status=status.HTTP_401_UNAUTHORIZED)
            
            # Signature valide - log de succès
            logger.info(
                "didit_webhook_signature_verified",
                request_id=request_id,
                ip_address=ip_address
            )
            
            # Créer audit log initial (sera mis à jour après traitement)
            audit_log = WebhookAuditLog.objects.create(
                request_id=request_id,
                didit_status=didit_status,
                ip_address=ip_address,
                user_agent=user_agent,
                payload_size=payload_size,
                signature_valid=True,
                signature_received=signature[:20],
                webhook_status='received',
                raw_payload=webhook_data
            )
            
            # Traitement du webhook
            logger.info("didit_webhook_processing_started", request_id=request_id)
            result = didit_webhook_service.process_kyc_webhook(webhook_data)
            
            # Calculer la durée de traitement
            processing_duration_ms = int((time.time() - start_time) * 1000)
            
            if result["success"]:
                # Mettre à jour l'audit log avec le succès
                audit_log.webhook_status = 'processed'
                audit_log.processing_duration_ms = processing_duration_ms
                if result.get("user_id"):
                    from Accounts.models import User
                    try:
                        audit_log.user = User.objects.get(id=result["user_id"])
                    except User.DoesNotExist:
                        pass
                audit_log.save()
                
                logger.info(
                    "didit_webhook_processing_completed",
                    request_id=request_id,
                    processing_duration_ms=processing_duration_ms,
                    user_id=result.get("user_id")
                )
                
                return Response(
                    {"status": "success", "message": result.get("message")},
                    status=status.HTTP_200_OK
                )
            else:
                # Mettre à jour l'audit log avec l'échec
                audit_log.webhook_status = 'failed'
                audit_log.processing_duration_ms = processing_duration_ms
                audit_log.error_message = result.get("error", "Unknown error")
                audit_log.save()
                
                logger.warning(
                    "didit_webhook_processing_failed",
                    request_id=request_id,
                    processing_duration_ms=processing_duration_ms,
                    error=result.get("error")
                )
                
                return Response(
                    {"status": "error", "message": result.get("error")},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            processing_duration_ms = int((time.time() - start_time) * 1000)
            
            logger.error(
                "didit_webhook_processing_error",
                error=str(e),
                request_id=request_id if 'request_id' in locals() else "unknown",
                processing_duration_ms=processing_duration_ms
            )
            
            # Créer ou mettre à jour l'audit log avec l'erreur
            if audit_log:
                audit_log.webhook_status = 'failed'
                audit_log.processing_duration_ms = processing_duration_ms
                audit_log.error_message = str(e)
                audit_log.save()
            else:
                WebhookAuditLog.objects.create(
                    request_id=request_id if 'request_id' in locals() else "unknown",
                    didit_status=didit_status if 'didit_status' in locals() else "",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    payload_size=payload_size,
                    signature_valid=False,
                    webhook_status='failed',
                    processing_duration_ms=processing_duration_ms,
                    error_message=str(e),
                    raw_payload=webhook_data if 'webhook_data' in locals() else {}
                )
            
            return Response(
                {"status": "error", "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

