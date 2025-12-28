from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle
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
    """
    Endpoint: POST /api/auth/phone/
    
    Envoie un code OTP via Didit et détermine register/login.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    
    def post(self, request):
        # Log de la requête
        logger.info(
            "phone_auth_request",
            ip=self._get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:100]
        )
        
        # Validation des données
        serializer = PhoneAuthSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(
                "phone_auth_validation_failed",
                errors=serializer.errors
            )
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )
        
        phone_number = serializer.validated_data['phone_number']
        country_code = serializer.validated_data['country_code']
        
        # Vérifier l'existence de l'utilisateur
        try:
            user = User.objects.get(phone_number=phone_number)
            action = 'login'
            
            # Vérifications de sécurité
            if not user.is_active:
                logger.warning(
                    "inactive_account_attempt",
                    phone_number=self._mask_phone(phone_number),
                    user_id=str(user.id)
                )
                return Response({
                    "error": "Ce compte a été désactivé",
                    "code": "account_disabled"
                }, status=status.HTTP_403_FORBIDDEN)
                
        except User.DoesNotExist:
            user = None
            action = 'register'
        
        # Vérifier les tentatives récentes (rate limiting custom)
        if self._is_rate_limited(phone_number):
            logger.warning(
                "rate_limited_attempt",
                phone_number=self._mask_phone(phone_number)
            )
            return Response({
                "error": "Trop de tentatives récentes",
                "code": "rate_limited",
                "retry_after": 300  # secondes
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)
        
        # Préparer les données pour Didit
        vendor_data = str(user.id) if user else None
        
        # Extraire les métadonnées
        request_meta = self._extract_request_metadata(request)
        
        # Appel au service Didit
        result = didit_service.send_verification_code(
            phone_number=phone_number,
            request_meta=request_meta,
            vendor_data=vendor_data
        )
        
        # Gestion des réponses Didit
        if not result["success"]:
            logger.warning(
                "didit_send_failed",
                phone_number=self._mask_phone(phone_number),
                reason=result.get("reason"),
                didit_status=result.get("status")
            )
            
            # Enregistrer l'échec pour le rate limiting
            self._record_attempt(phone_number, success=False)
            
            return Response({
                "error": result["message"],
                "code": result["reason"],
                "status": result["status"]
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Créer une session sécurisée
        session_key = self._create_session(
            phone_number=phone_number,
            country_code=country_code,
            action=action,
            user=user,
            request_id=result["request_id"],
            request_meta=request_meta
        )
        
        # Enregistrer le succès
        self._record_attempt(phone_number, success=True)
        
        # Préparer la réponse
        response_data = self._prepare_auth_response(
            phone_number=phone_number,
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
    
    def _get_client_ip(self, request):
        """Récupère l'IP réelle du client"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '')
        return ip
    
    def _extract_request_metadata(self, request):
        """Extrait les métadonnées de la requête"""
        return {
            'REMOTE_ADDR': self._get_client_ip(request),
            'HTTP_USER_AGENT': request.META.get('HTTP_USER_AGENT', ''),
            'HTTP_X_DEVICE_ID': request.META.get('HTTP_X_DEVICE_ID', ''),
            'HTTP_X_APP_VERSION': request.META.get('HTTP_X_APP_VERSION', ''),
        }
    
    def _create_session(self, phone_number, country_code, action, user, request_id, request_meta):
        """Crée une session sécurisée"""
        session_key = f"auth_{uuid.uuid4().hex[:16]}"
        expires_at = timezone.now() + timezone.timedelta(minutes=5)
        
        session_data = {
            "phone_number": phone_number,
            "country_code": country_code,
            "action": action,
            "request_id": request_id,
            "user_id": str(user.id) if user else None,
            "user_exists": user is not None,
            "request_meta": request_meta,
            "created_at": timezone.now().isoformat(),
            "expires_at": expires_at.isoformat(),
            "attempts": 0  # Compteur de tentatives de vérification
        }
        
        # Stocker en cache pour 5 minutes
        cache.set(session_key, session_data, timeout=300)
        
        # Stocker également une référence par phone_number (pour retrouver la session)
        phone_sessions_key = f"phone_sessions_{phone_number}"
        phone_sessions = cache.get(phone_sessions_key, [])
        phone_sessions.append(session_key)
        # Garder seulement les 3 dernières sessions
        cache.set(phone_sessions_key, phone_sessions[-3:], timeout=300)
        
        return session_key
    
    def _prepare_auth_response(self, phone_number, action, user, session_key, request_id, didit_result):
        """Prépare la réponse d'authentification"""
        response_data = {
            "success": True,
            "action": action,
            "message": didit_result["message"],
            "session_key": session_key,
            "request_id": request_id,
            "phone_number": phone_number,
            "user_exists": user is not None,
            "expires_in": 300,  # secondes
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
                "is_verified": user.is_verified
            }
        
        return response_data
    
    def _is_rate_limited(self, phone_number):
        """Vérifie si le numéro est rate limited"""
        attempts_key = f"auth_attempts_{phone_number}"
        attempts = cache.get(attempts_key, [])
        
        # Garder seulement les tentatives des 10 dernières minutes
        now = timezone.now()
        recent_attempts = [
            attempt_time for attempt_time in attempts 
            if (now - attempt_time).total_seconds() < 600
        ]
        
        # Plus de 5 tentatives dans les 10 dernières minutes
        if len(recent_attempts) >= 5:
            return True
        
        # Mettre à jour le cache
        cache.set(attempts_key, recent_attempts, timeout=600)
        return False
    
    def _record_attempt(self, phone_number, success):
        """Enregistre une tentative d'authentification"""
        attempts_key = f"auth_attempts_{phone_number}"
        attempts = cache.get(attempts_key, [])
        attempts.append(timezone.now())
        cache.set(attempts_key, attempts, timeout=600)
    
    def _mask_phone(self, phone_number):
        """Masque le numéro pour les logs"""
        if len(phone_number) > 6:
            return phone_number[:4] + "****" + phone_number[-2:]
        return "****"


class VerifyOTPView(APIView):
    """
    Endpoint: POST /api/auth/verify/
    
    Vérifie le code OTP et authentifie l'utilisateur.
    Compatible avec Didit V2 : vérification directe via phone + code.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    
    def post(self, request):
        # Validation des données entrantes
        serializer = VerifyOTPSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(
                "verify_otp_validation_failed",
                errors=serializer.errors
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        phone_number = serializer.validated_data['phone_number']
        code = serializer.validated_data['code']
        session_key = serializer.validated_data.get('session_key')
        
        session_data = None
        if session_key:
            session_data = cache.get(session_key)
            if not session_data:
                return Response({
                    "error": "Session expirée",
                    "code": "session_expired"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Vérification de cohérence du numéro
            if session_data.get('phone_number') != phone_number:
                logger.warning(
                    "phone_number_mismatch",
                    session_phone=session_data.get('phone_number'),
                    provided_phone=phone_number
                )
                return Response({
                    "error": "Incohérence de session",
                    "code": "session_mismatch"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Limite de tentatives par session
            attempts = session_data.get('attempts', 0)
            if attempts >= 3:
                logger.warning(
                    "max_attempts_reached",
                    phone_number=self._mask_phone(phone_number),
                    session_key=session_key[:8] + "..."
                )
                return Response({
                    "error": "Trop de tentatives échouées",
                    "code": "max_attempts_exceeded"
                }, status=status.HTTP_429_TOO_MANY_REQUESTS)
        
        # Vérification du code auprès de Didit (nouvelle API : phone + code)
        verify_result = didit_service.verify_code(phone_number, code)
        
        # Log de la tentative
        logger.info(
            "verify_otp_attempt",
            phone_number=self._mask_phone(phone_number),
            success=verify_result.get("success", False),
            verified=verify_result.get("verified", False),
            didit_status=verify_result.get("status")
        )
        
        # Échec réseau ou technique avec Didit
        if not verify_result["success"]:
            if session_data:
                session_data['attempts'] = session_data.get('attempts', 0) + 1
                cache.set(session_key, session_data, timeout=300)
            
            return Response({
                "error": verify_result.get("message", "Échec de la vérification"),
                "code": "verification_failed"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Code invalide ou numéro refusé (disposable, VoIP, duplicate, etc.)
        if not verify_result["verified"]:
            if session_data:
                session_data['attempts'] = session_data.get('attempts', 0) + 1
                cache.set(session_key, session_data, timeout=300)
            
            remaining = 3 - session_data.get('attempts', 0) - 1 if session_data else 2
            return Response({
                "error": "Code de vérification invalide",
                "code": "invalid_otp",
                "remaining_attempts": max(0, remaining)
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # === VÉRIFICATION RÉUSSIE ===
        phone_details = verify_result.get("phone_details", {})
        didit_status = verify_result.get("status")  # "Approved"

        # Récupérer action et country_code
        if session_data:
            action = session_data.get('action')
            country_code = session_data.get('country_code')
        else:
            action = 'login' if User.objects.filter(phone_number=phone_number).exists() else 'register'
            country_code = phone_details.get("phone_number_prefix", '+33')

        # Gestion de l'utilisateur
        if action == 'login':
            try:
                user = User.objects.get(phone_number=phone_number)
            except User.DoesNotExist:
                logger.error("user_not_found_on_login", phone_number=self._mask_phone(phone_number))
                return Response({
                    "error": "Utilisateur introuvable",
                    "code": "user_not_found"
                }, status=status.HTTP_404_NOT_FOUND)
        else:  # register
            user = User.objects.create_user(
                phone_number=phone_number,
                country_code=country_code or phone_details.get("phone_number_prefix", '+33'),
                kyc_status='unverified',
                is_verified=False
            )
            user.set_unusable_password()
            user.save()
            
            logger.info(
                "user_created",
                user_id=str(user.id),
                phone_number=self._mask_phone(phone_number)
            )

        # Mise à jour des infos depuis Didit (si pertinent)
        if phone_details:
            if not user.country_code and phone_details.get("phone_number_prefix"):
                user.country_code = phone_details["phone_number_prefix"]
            # Vous pouvez enrichir le modèle User avec carrier, is_disposable, etc. si besoin
            user.save()

        # Mise à jour du dernier login
        user.last_login = timezone.now()
        user.save()

        # Nettoyage de la session
        if session_key:
            cache.delete(session_key)

        # Génération du token d'authentification
        auth_token = self._create_auth_token(user)

        # Sérialisation de l'utilisateur
        user_serializer = UserSerializer(user)

        # Réponse finale
        response_data = {
            "success": True,
            "action": action,
            "message": "Authentification réussie",
            "user": user_serializer.data,
            "auth": {
                "token": auth_token,
                "expires_in": 86400,
                "type": "bearer"
            },
            "kyc_info": {
                "status": user.kyc_status,
                "is_verified": user.is_verified,
                "required": True,
                "next_step": "complete_profile" if user.kyc_status == "unverified" else "ready"
            },
            "otp_verified": True,
            "metadata": {
                "verified_at": timezone.now().isoformat(),
                "verification_method": phone_details.get("verification_method", "sms")
            },
            "didit_details": {
                "status": didit_status,
                "message": verify_result.get("message"),
                "phone": {
                    "country_code": phone_details.get("country_code"),
                    "country_name": phone_details.get("country_name"),
                    "carrier": phone_details.get("carrier"),
                    "is_disposable": phone_details.get("is_disposable", False),
                    "is_virtual": phone_details.get("is_virtual", False),
                    "warnings": phone_details.get("warnings", [])
                }
            }
        }
        
        logger.info(
            "verify_otp_success",
            action=action,
            user_id=str(user.id),
            phone_number=self._mask_phone(phone_number),
            didit_status=didit_status,
            is_disposable=phone_details.get("is_disposable", False),
            is_virtual=phone_details.get("is_virtual", False)
        )
        
        return Response(response_data, status=status.HTTP_200_OK)
    
    def _create_auth_token(self, user):
        """Génère un token simple (à remplacer par JWT ou DRF Token en prod)"""
        token = f"usr_{user.id}_{uuid.uuid4().hex[:16]}"
        cache.set(f"auth_token_{token}", {
            "user_id": str(user.id),
            "created_at": timezone.now().isoformat(),
            "phone_number": user.phone_number
        }, timeout=86400)
        return token
    
    def _mask_phone(self, phone_number):
        """Masque le numéro pour les logs"""
        if len(phone_number or "") > 6:
            return phone_number[:4] + "****" + phone_number[-2:]
        return "****"

class ResendOTPView(APIView):
    """
    Endpoint: POST /api/auth/resend/
    
    Renvoie un code OTP.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    
    def post(self, request):
        serializer = ResendOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )
        
        session_key = serializer.validated_data['session_key']
        session_data = cache.get(session_key)
        
        if not session_data:
            return Response({
                "error": "Session expirée",
                "code": "session_expired"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        phone_number = session_data['phone_number']
        request_id = session_data['request_id']
        
        # Appeler Didit pour renvoyer le code
        result = didit_service.resend_code(request_id)
        
        if not result["success"]:
            return Response({
                "error": result["message"],
                "code": "resend_failed"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Mettre à jour la session avec le nouveau request_id
        if result.get("request_id"):
            session_data["request_id"] = result["request_id"]
            session_data["resent_at"] = timezone.now().isoformat()
            session_data["resent_count"] = session_data.get("resent_count", 0) + 1
            cache.set(session_key, session_data, timeout=cache.ttl(session_key))
        
        logger.info(
            "otp_resent",
            phone_number=self._mask_phone(phone_number),
            session_key=session_key[:8] + "...",
            resent_count=session_data.get("resent_count", 1)
        )
        
        return Response({
            "success": True,
            "message": "Code renvoyé avec succès",
            "request_id": result.get("request_id", request_id),
            "session_key": session_key,
            "expires_in": cache.ttl(session_key)
        })
    
    def _mask_phone(self, phone_number):
        """Masque le numéro pour les logs"""
        if len(phone_number) > 6:
            return phone_number[:4] + "****" + phone_number[-2:]
        return "****"


class AuthStatusView(APIView):
    """
    Endpoint: GET /api/auth/status/
    
    Vérifie le statut d'une session.
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        session_key = request.query_params.get('session_key')
        
        if not session_key:
            return Response({
                "authenticated": False,
                "message": "Session non fournie"
            })
        
        session_data = cache.get(session_key)
        
        if not session_data:
            return Response({
                "authenticated": False,
                "message": "Session expirée"
            })
        
        # Vérifier si l'utilisateur existe et est actif
        user_id = session_data.get('user_id')
        user = None
        if user_id:
            try:
                user = User.objects.get(id=user_id, is_active=True)
            except User.DoesNotExist:
                pass
        
        response_data = {
            "authenticated": True,
            "session": {
                "phone_number": session_data.get('phone_number'),
                "action": session_data.get('action'),
                "user_exists": session_data.get('user_exists', False),
                "created_at": session_data.get('created_at'),
                "expires_in": cache.ttl(session_key)
            },
            "user": UserSerializer(user).data if user else None
        }
        
        return Response(response_data)