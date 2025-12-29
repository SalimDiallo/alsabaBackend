from rest_framework.permissions import IsAuthenticated
from django.core.cache import cache
from ..models import User
from ..Serializers.delete import AccountDeleteSerializer, AccountDeleteConfirmSerializer
from ..Services.OTP_services import didit_service  # ton service OTP existant
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import uuid
from django.utils import timezone
import structlog
logger = structlog.get_logger(__name__)
class AccountDeleteRequestView(APIView):
    """
    POST /api/account/delete/
    Demande de suppression → envoi OTP
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AccountDeleteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        
        # Création d'une session temporaire pour la suppression
        session_key = f"delete_{uuid.uuid4().hex[:16]}"
        expires_at = timezone.now() + timezone.timedelta(minutes=10)
        
        session_data = {
            "user_id": str(user.id),
            "full_phone_number": user.full_phone_number,
            "reason": serializer.validated_data.get('reason', "user_requested"),
            "created_at": timezone.now().isoformat(),
            "expires_at": expires_at.isoformat(),
            "attempts": 0
        }
        
        cache.set(session_key, session_data, timeout=600)  # 10 min
        
        # Envoi OTP via Didit (comme pour l'auth)
        result = didit_service.send_verification_code(
            phone_number=user.full_phone_number,
            request_meta=self._extract_request_metadata(request),
            vendor_data=str(user.id) + "_delete"
        )
        
        if not result["success"]:
            cache.delete(session_key)
            return Response({
                "error": result["message"],
                "code": "otp_send_failed"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        logger.info("account_delete_request", user_id=str(user.id), session_key=session_key[:8])
        
        return Response({
            "success": True,
            "message": "Un code de confirmation a été envoyé par SMS.",
            "session_key": session_key,
            "expires_in": 600,
            "next_step": "enter_code"
        })
    
    def _extract_request_metadata(self, request):
        """Extrait les métadonnées de la requête pour Didit"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '')
        
        return {
            'REMOTE_ADDR': ip,
            'HTTP_USER_AGENT': request.META.get('HTTP_USER_AGENT', ''),
            'HTTP_X_DEVICE_ID': request.META.get('HTTP_X_DEVICE_ID', ''),
            'HTTP_X_APP_VERSION': request.META.get('HTTP_X_APP_VERSION', ''),
        }

class AccountDeleteConfirmView(APIView):
    """
    POST /api/account/delete/confirm/
    Vérifie OTP et effectue soft delete
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AccountDeleteConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        session_key = serializer.validated_data['session_key']
        code = serializer.validated_data['code']
        
        session_data = cache.get(session_key)
        if not session_data:
            return Response({"error": "Session expirée", "code": "session_expired"}, status=status.HTTP_400_BAD_REQUEST)

        user_id = session_data['user_id']
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            cache.delete(session_key)
            return Response({"error": "Utilisateur introuvable"}, status=status.HTTP_404_NOT_FOUND)

        # Vérification OTP
        verify_result = didit_service.verify_code(user.full_phone_number, code)
        
        if not verify_result["success"] or not verify_result["verified"]:
            session_data['attempts'] = session_data.get('attempts', 0) + 1
            cache.set(session_key, session_data, timeout=600)
            
            if session_data['attempts'] >= 3:
                cache.delete(session_key)
                return Response({"error": "Trop de tentatives", "code": "max_attempts"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            
            return Response({
                "error": "Code invalide",
                "remaining_attempts": 3 - session_data['attempts']
            }, status=status.HTTP_400_BAD_REQUEST)

        # === OTP VALIDE → SOFT DELETE ===
        user.soft_delete(reason=session_data['reason'])
        cache.delete(session_key)
        
        logger.info("account_soft_deleted", user_id=str(user.id), reason=session_data['reason'])
        
        return Response({
            "success": True,
            "message": "Votre compte a été supprimé avec succès. Au revoir !",
            "action": "account_deleted"
        }, status=status.HTTP_200_OK)