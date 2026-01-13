from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.core.cache import cache
from ..models import User
from ..Services.OTP_services import didit_service
from ..utils import AuthUtils as auth_utils
import structlog
logger = structlog.get_logger(__name__)
class AccountDeleteRequestView(APIView):
    """
    POST /api/account/delete/
    Demande de suppression → envoi OTP de confirmation
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Initie une demande de suppression de compte.
        Envoie un code OTP de confirmation.
        """
        from ..Serializers.delete import AccountDeleteSerializer
        
        serializer = AccountDeleteSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(
                "delete_request_validation_failed",
                user_id=str(request.user.id),
                errors=serializer.errors
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        
        # Vérifier si une demande de suppression est déjà en cours
        existing_session_key = f"delete_pending_{user.id}"
        existing_session = cache.get(existing_session_key)
        if existing_session:
            expires_in = cache.ttl(existing_session_key)
            return Response({
                "success": True,
                "message": "Une demande de suppression est déjà en cours",
                "session_key": existing_session.get('session_key'),
                "expires_in": expires_in,
                "next_step": "enter_code"
            })

        # Vérification du rate limiting pour la suppression
        if auth_utils.is_rate_limited(f"delete_{user.id}", limit=3, window_seconds=3600):
            return Response({
                "error": "Trop de demandes de suppression récentes",
                "code": "delete_rate_limited",
                "retry_after": 3600
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Création d'une session de suppression
        session_key = auth_utils.generate_session_key("delete")
        expires_at = timezone.now() + timezone.timedelta(minutes=10)
        
        session_data = {
            "user_id": str(user.id),
            "full_phone_number": user.full_phone_number,
            "reason": serializer.validated_data.get('reason', 'user_requested'),
            "ip_address": auth_utils.get_client_ip(request),
            "user_agent": request.META.get('HTTP_USER_AGENT', '')[:200],
            "created_at": timezone.now().isoformat(),
            "expires_at": expires_at.isoformat(),
            "attempts": 0,
            "confirmed": False
        }
        
        # Stocker la session principale
        cache.set(session_key, session_data, timeout=600)
        
        # Stocker une référence pour éviter les doublons
        cache.set(f"delete_pending_{user.id}", {
            "session_key": session_key,
            "created_at": session_data["created_at"]
        }, timeout=600)

        # Préparation des métadonnées pour Didit
        request_meta = auth_utils.extract_request_metadata(request)
        vendor_data = f"{user.id}_delete"

        # Envoi OTP via Didit
        result = didit_service.send_verification_code(
            phone_number=user.full_phone_number,
            request_meta=request_meta,
            vendor_data=vendor_data
        )
        
        if not result["success"]:
            # Nettoyer les sessions en cas d'échec
            cache.delete(session_key)
            cache.delete(f"delete_pending_{user.id}")
            
            logger.warning(
                "delete_otp_send_failed",
                user_id=str(user.id),
                reason=result.get("reason")
            )
            
            return Response({
                "error": result.get("message", "Échec d'envoi du code de confirmation"),
                "code": "otp_send_failed"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Mettre à jour la session avec le request_id Didit
        session_data["request_id"] = result["request_id"]
        cache.set(session_key, session_data, timeout=600)
        
        logger.info(
            "account_delete_requested",
            user_id=str(user.id),
            session_key=session_key[:8] + "...",
            reason=session_data["reason"]
        )
        
        return Response({
            "success": True,
            "message": "Un code de confirmation a été envoyé par SMS.",
            "session_key": session_key,
            "expires_in": 600,
            "next_step": "enter_code",
            "warning": "Cette action est irréversible. Votre compte et toutes les données associées seront supprimés."
        })
class AccountDeleteConfirmView(APIView):
    """
    POST /api/account/delete/confirm/
    Vérifie OTP et effectue soft delete
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Confirme la suppression de compte avec le code OTP.
        Effectue un soft delete de l'utilisateur.
        """
        from ..Serializers.delete import AccountDeleteConfirmSerializer
        
        serializer = AccountDeleteConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        session_key = serializer.validated_data['session_key']
        code = serializer.validated_data['code']
        
        # Récupération de la session
        session_data = cache.get(session_key)
        if not session_data:
            return Response({
                "error": "Session expirée ou invalide",
                "code": "session_expired"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Vérification de l'utilisateur
        user_id = session_data['user_id']
        try:
            user = User.objects.get(id=user_id)
            if user.id != request.user.id:
                logger.warning(
                    "delete_user_mismatch",
                    session_user=user_id,
                    request_user=str(request.user.id)
                )
                return Response({
                    "error": "Incohérence d'authentification",
                    "code": "user_mismatch"
                }, status=status.HTTP_403_FORBIDDEN)
        except User.DoesNotExist:
            cache.delete(session_key)
            cache.delete(f"delete_pending_{user_id}")
            return Response({
                "error": "Utilisateur introuvable"
            }, status=status.HTTP_404_NOT_FOUND)

        # Vérification du nombre de tentatives
        if session_data.get('attempts', 0) >= 3:
            # Nettoyer et bloquer
            cache.delete(session_key)
            cache.delete(f"delete_pending_{user_id}")
            
            # Rate limiting supplémentaire
            auth_utils.is_rate_limited(f"delete_attempts_{user_id}", limit=1, window_seconds=86400)
            
            return Response({
                "error": "Trop de tentatives échouées",
                "code": "max_attempts",
                "next_step": "contact_support"
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Vérification OTP via Didit
        request_id = session_data.get('request_id')
        verify_result = didit_service.verify_code(
            phone_number=user.full_phone_number,
            code=code,
            request_id=request_id
        )
        
        if not verify_result["success"] or not verify_result["verified"]:
            # Incrémenter les tentatives
            session_data['attempts'] = session_data.get('attempts', 0) + 1
            session_data['last_attempt'] = timezone.now().isoformat()
            cache.set(session_key, session_data, timeout=cache.ttl(session_key) or 600)
            
            remaining = 3 - session_data['attempts']
            logger.warning(
                "delete_otp_failed",
                user_id=str(user.id),
                attempts=session_data['attempts'],
                remaining=remaining
            )
            
            return Response({
                "error": "Code de confirmation invalide",
                "code": "invalid_otp",
                "remaining_attempts": remaining
            }, status=status.HTTP_400_BAD_REQUEST)

        # === OTP VALIDE → SOFT DELETE ===
        try:
            # Soft delete de l'utilisateur
            deletion_reason = session_data.get('reason', 'user_requested')
            user.soft_delete(reason=deletion_reason)
            
            # Nettoyer les sessions
            cache.delete(session_key)
            cache.delete(f"delete_pending_{user_id}")
            
            # Invalider les tokens JWT actifs
            self._invalidate_user_tokens(user)
            
            logger.info(
                "account_soft_deleted",
                user_id=str(user.id),
                reason=deletion_reason,
                deleted_at=user.deleted_at.isoformat() if user.deleted_at else None
            )
            
            return Response({
                "success": True,
                "message": "Votre compte a été supprimé avec succès. Au revoir !",
                "action": "account_deleted",
                "metadata": {
                    "deleted_at": timezone.now().isoformat(),
                    "recovery_possible_until": (
                        (timezone.now() + timezone.timedelta(days=30)).isoformat()
                        if hasattr(user, 'recovery_possible_until') else None
                    )
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(
                "delete_processing_error",
                user_id=str(user.id),
                error=str(e)
            )
            return Response({
                "error": "Erreur lors de la suppression du compte",
                "code": "processing_error"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _invalidate_user_tokens(self, user):
        """
        Invalide les tokens JWT de l'utilisateur.
        Note: Cette fonctionnalité dépend de la configuration de Simple JWT.
        """
        try:
            # Invalider le refresh token si stocké
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
            
            tokens = OutstandingToken.objects.filter(user=user)
            for token in tokens:
                BlacklistedToken.objects.get_or_create(token=token)
                
            logger.debug("tokens_invalidated", user_id=str(user.id), count=tokens.count())
            
        except Exception as e:
            # Log mais continuer même si l'invalidation échoue
            logger.warning("token_invalidation_failed", error=str(e))