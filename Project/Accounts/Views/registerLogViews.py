# apps/auth/views.py (ou où tu places tes vues)

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils import timezone
from django.core.cache import cache
import uuid
import structlog

from ..Serializers.OTP_serializers import (
    PhoneAuthSerializer,
    VerifyOTPSerializer,
    ResendOTPSerializer,
    UserSerializer
)
from ..Services.OTP_services import didit_service
from ..models import User

logger = structlog.get_logger(__name__)


class PhoneAuthView(APIView):
    permission_classes = [AllowAny]
    #throttle_classes = [AnonRateThrottle]

    def post(self, request):
        logger.info(
            "phone_auth_request",
            ip=self._get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:100]
        )

        serializer = PhoneAuthSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("phone_auth_validation_failed", errors=serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # On récupère le numéro déjà normalisé en E.164 par le serializer
        full_phone_number = serializer.validated_data['phone_number']
        country_code = serializer.validated_data['country_code']

        # Recherche utilisateur par full_phone_number
        try:
            user = User.objects.get(full_phone_number=full_phone_number)
            action = 'login'
            if not user.is_active:
                logger.warning("inactive_account_attempt", phone_number=self._mask_phone(full_phone_number))
                return Response({
                    "error": "Ce compte a été désactivé",
                    "code": "account_disabled"
                }, status=status.HTTP_403_FORBIDDEN)
        except User.DoesNotExist:
            user = None
            action = 'register'

        # Rate limiting custom
        if self._is_rate_limited(full_phone_number):
            logger.warning("rate_limited_attempt", phone_number=self._mask_phone(full_phone_number))
            return Response({
                "error": "Trop de tentatives récentes",
                "code": "rate_limited",
                "retry_after": 300
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Métadonnées pour Didit
        request_meta = self._extract_request_metadata(request)
        vendor_data = str(user.id) if user else None

        # Envoi du code via Didit
        result = didit_service.send_verification_code(
            phone_number=full_phone_number,
            request_meta=request_meta,
            vendor_data=vendor_data
        )

        if not result["success"]:
            logger.warning(
                "didit_send_failed",
                phone_number=self._mask_phone(full_phone_number),
                reason=result.get("reason")
            )
            self._record_attempt(full_phone_number, success=False)
            return Response({
                "error": result["message"],
                "code": result["reason"],
            }, status=status.HTTP_400_BAD_REQUEST)

        # Création session
        session_key = self._create_session(
            full_phone_number=full_phone_number,
            country_code=country_code,
            action=action,
            user=user,
            request_id=result["request_id"],
            request_meta=request_meta
        )

        self._record_attempt(full_phone_number, success=True)

        response_data = self._prepare_auth_response(
            full_phone_number=full_phone_number,
            action=action,
            user=user,
            session_key=session_key,
            request_id=result["request_id"],
            didit_result=result
        )

        logger.info(
            "phone_auth_success",
            action=action,
            user_exists=user is not None,
            session_key=session_key[:8] + "..."
        )

        return Response(response_data, status=status.HTTP_200_OK)

    # Méthodes utilitaires (inchangées sauf mask_phone)
    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')

    def _extract_request_metadata(self, request):
        return {
            'REMOTE_ADDR': self._get_client_ip(request),
            'HTTP_USER_AGENT': request.META.get('HTTP_USER_AGENT', ''),
            'HTTP_X_DEVICE_ID': request.META.get('HTTP_X_DEVICE_ID', ''),
            'HTTP_X_APP_VERSION': request.META.get('HTTP_X_APP_VERSION', ''),
        }

    def _create_session(self, full_phone_number, country_code, action, user, request_id, request_meta):
        session_key = f"auth_{uuid.uuid4().hex[:16]}"
        expires_at = timezone.now() + timezone.timedelta(minutes=5)

        session_data = {
            "full_phone_number": full_phone_number,
            "country_code": country_code,
            "action": action,
            "request_id": request_id,
            "user_id": str(user.id) if user else None,
            "user_exists": user is not None,
            "request_meta": request_meta,
            "created_at": timezone.now().isoformat(),
            "expires_at": expires_at.isoformat(),
            "attempts": 0
        }

        cache.set(session_key, session_data, timeout=300)

        phone_sessions_key = f"phone_sessions_{full_phone_number}"
        phone_sessions = cache.get(phone_sessions_key, [])
        phone_sessions.append(session_key)
        cache.set(phone_sessions_key, phone_sessions[-3:], timeout=300)

        return session_key

    def _prepare_auth_response(self, full_phone_number, action, user, session_key, request_id, didit_result):
        response_data = {
            "success": True,
            "action": action,
            "message": didit_result["message"],
            "session_key": session_key,
            "request_id": request_id,
            "phone_number": full_phone_number,
            "user_exists": user is not None,
            "expires_in": 300,
            "metadata": {
                "code_size": 6,
                "channel": "sms",
                "max_attempts": 3
            }
        }

        if user:
            response_data["user"] = {
                "id": str(user.id),
                "kyc_status": user.kyc_status,
                "phone_verified": user.phone_verified
            }

        return response_data

    def _is_rate_limited(self, full_phone_number):
        attempts_key = f"auth_attempts_{full_phone_number}"
        attempts = cache.get(attempts_key, [])
        now = timezone.now()
        recent_attempts = [t for t in attempts if (now - t).total_seconds() < 600]
        if len(recent_attempts) >= 5:
            return True
        cache.set(attempts_key, recent_attempts, timeout=600)
        return False

    def _record_attempt(self, full_phone_number, success):
        attempts_key = f"auth_attempts_{full_phone_number}"
        attempts = cache.get(attempts_key, [])
        attempts.append(timezone.now())
        cache.set(attempts_key, attempts, timeout=600)

    def _mask_phone(self, phone_number):
        if len(phone_number or "") > 10:
            return phone_number[:6] + "****" + phone_number[-2:]
        return "****"

class VerifyOTPView(APIView):
    permission_classes = [AllowAny]
    #throttle_classes = [AnonRateThrottle]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("verify_otp_validation_failed", errors=serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        full_phone_number = serializer.validated_data['phone_number']
        code = serializer.validated_data['code']
        session_key = serializer.validated_data.get('session_key')

        session_data = None
        if session_key:
            session_data = cache.get(session_key)
            if not session_data:
                return Response({"error": "Session expirée", "code": "session_expired"}, status=status.HTTP_400_BAD_REQUEST)

            if session_data.get('full_phone_number') != full_phone_number:
                return Response({"error": "Incohérence de session", "code": "session_mismatch"}, status=status.HTTP_400_BAD_REQUEST)

            if session_data.get('attempts', 0) >= 3:
                return Response({"error": "Trop de tentatives échouées", "code": "max_attempts_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Vérification Didit
        verify_result = didit_service.verify_code(full_phone_number, code)

        logger.info(
            "verify_otp_attempt",
            phone_number=self._mask_phone(full_phone_number),
            success=verify_result.get("success", False),
            verified=verify_result.get("verified", False)
        )

        if not verify_result["success"]:
            if session_data:
                session_data['attempts'] = session_data.get('attempts', 0) + 1
                cache.set(session_key, session_data, timeout=300)
            return Response({
                "error": verify_result.get("message", "Échec de la vérification"),
                "code": "verification_failed"
            }, status=status.HTTP_400_BAD_REQUEST)

        if not verify_result["verified"]:
            if session_data:
                session_data['attempts'] = session_data.get('attempts', 0) + 1
                cache.set(session_key, session_data, timeout=300)
            remaining = 3 - (session_data.get('attempts', 0) + 1) if session_data else 2
            return Response({
                "error": "Code de vérification invalide",
                "code": "invalid_otp",
                "remaining_attempts": max(0, remaining)
            }, status=status.HTTP_400_BAD_REQUEST)

        # === SUCCÈS ===
        phone_details = verify_result.get("phone_details", {})
        didit_status = verify_result.get("status")

        # Blocage des numéros jetables ou VOIP
        if phone_details.get("is_disposable") or phone_details.get("is_virtual"):
            logger.warning(
                "blocked_fraudulent_phone",
                phone_number=self._mask_phone(full_phone_number),
                is_disposable=phone_details.get("is_disposable"),
                is_voip=phone_details.get("is_virtual")
            )
            return Response({
                "error": "Les numéros temporaires ou virtuels ne sont pas autorisés",
                "code": "fraudulent_phone"
            }, status=status.HTTP_403_FORBIDDEN)

        # Récupérer action depuis session ou déduire
        action = session_data.get('action') if session_data else ('login' if User.objects.filter(full_phone_number=full_phone_number).exists() else 'register')
        country_code = session_data.get('country_code') if session_data else phone_details.get("phone_number_prefix", "+33")

        # Gestion utilisateur
        try:
            user = User.objects.get(full_phone_number=full_phone_number)
        except User.DoesNotExist:
            # Création si inscription
            if action == 'register':
                # Extraire le numéro national depuis phone_details ou fallback
                national_number = full_phone_number.replace(country_code, "", 1)  # Plus fiable
                user = User.objects.create_user(
                    phone_number=national_number,
                    country_code=country_code,
                )
                logger.info("user_created_via_otp", user_id=str(user.id))
            else:
                return Response({"error": "Utilisateur introuvable", "code": "user_not_found"}, status=status.HTTP_404_NOT_FOUND)

        # Mise à jour infos Didit + vérification téléphone
        user.carrier = phone_details.get("carrier", "")
        user.is_disposable = phone_details.get("is_disposable", False)
        user.is_voip = phone_details.get("is_virtual", False)
        user.phone_verified = True
        user.phone_verified_at = timezone.now()
        user.last_login = timezone.now()
        user.save()

        # Nettoyage session
        if session_key:
            cache.delete(session_key)

        # Génération des tokens JWT
        tokens = self._create_auth_token(user)

        user_serializer = UserSerializer(user)

        response_data = {
            "success": True,
            "action": action,
            "message": "Authentification réussie",
            "user": user_serializer.data,
            "auth": {
                "access_token": tokens['access'],
                "refresh_token": tokens['refresh'],
                "expires_in": 3600,  # 1 heure (configuré dans SIMPLE_JWT)
                "token_type": "bearer"
            },
            "kyc_info": {
                "status": user.kyc_status,
                "required": True,
                "next_step": "complete_profile" if user.kyc_status == "unverified" else "ready"
            },
            "otp_verified": True,
            "metadata": {
                "verified_at": timezone.now().isoformat(),
                "verification_method": phone_details.get("verification_method", "sms")
            }
        }

        logger.info(
            "verify_otp_success",
            action=action,
            user_id=str(user.id),
            phone_verified=True
        )

        return Response(response_data, status=status.HTTP_200_OK)

    def _create_auth_token(self, user):
        """
        Génère les tokens JWT (access + refresh) pour l'utilisateur.
        Utilise rest_framework_simplejwt qui est déjà configuré dans settings.
        """
        refresh = RefreshToken.for_user(user)
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }

    def _mask_phone(self, phone_number):
        if len(phone_number or "") > 10:
            return phone_number[:6] + "****" + phone_number[-2:]
        return "****"

class ResendOTPView(APIView):
    permission_classes = [AllowAny]
    #throttle_classes = [AnonRateThrottle]

    def post(self, request):
        serializer = ResendOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        session_key = serializer.validated_data['session_key']
        session_data = cache.get(session_key)

        if not session_data:
            return Response({"error": "Session expirée", "code": "session_expired"}, status=status.HTTP_400_BAD_REQUEST)

        full_phone_number = session_data['full_phone_number']
        request_id = session_data['request_id']

        result = didit_service.resend_code(request_id)

        if not result["success"]:
            return Response({"error": result["message"], "code": "resend_failed"}, status=status.HTTP_400_BAD_REQUEST)

        if result.get("request_id"):
            session_data["request_id"] = result["request_id"]
            session_data["resent_count"] = session_data.get("resent_count", 0) + 1
            cache.set(session_key, session_data, timeout=cache.ttl(session_key))

        logger.info("otp_resent", phone_number=self._mask_phone(full_phone_number), resent_count=session_data.get("resent_count", 1))

        return Response({
            "success": True,
            "message": "Code renvoyé avec succès",
            "request_id": result.get("request_id", request_id),
            "session_key": session_key,
            "expires_in": cache.ttl(session_key)
        })

    def _mask_phone(self, phone_number):
        if len(phone_number) > 10:
            return phone_number[:6] + "****" + phone_number[-2:]
        return "****"

class AuthStatusView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        session_key = request.query_params.get('session_key')
        if not session_key:
            return Response({"authenticated": False, "message": "Session non fournie"})

        session_data = cache.get(session_key)
        if not session_data:
            return Response({"authenticated": False, "message": "Session expirée"})

        user = None
        if session_data.get('user_id'):
            try:
                user = User.objects.get(id=session_data['user_id'], is_active=True)
            except User.DoesNotExist:
                pass

        return Response({
            "authenticated": True,
            "session": {
                "phone_number": session_data.get('full_phone_number'),
                "action": session_data.get('action'),
                "user_exists": session_data.get('user_exists', False),
                "expires_in": cache.ttl(session_key)
            },
            "user": UserSerializer(user).data if user else None
        })