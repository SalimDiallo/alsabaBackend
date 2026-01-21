# apps/auth/views.py - Partie PhoneAuthView
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.utils import timezone
from django.core.cache import cache
import structlog
from rest_framework.permissions import IsAuthenticated
from ..utils import auth_utils
from ..Serializers.OTP_serializers import PhoneAuthSerializer, VerifyOTPSerializer
#from ..Services.OTP_services import didit_service
from Project.settings import DIDIT_USE_PLACEHOLDER
if DIDIT_USE_PLACEHOLDER:
    from ..Services.placeholders.OTP import didit_service
else:
    from ..Services.OTP_services import didit_service
from ..models import User

logger = structlog.get_logger(__name__)


class PhoneAuthView(APIView):
    """
    Vue pour l'authentification par téléphone (envoi du code OTP)
    POST /api/auth/phone/
    """
    permission_classes = [AllowAny]

    def post(self, request):
        """
        Envoie un code OTP au numéro de téléphone fourni.
        
        Flow:
        1. Validation du numéro
        2. Vérification utilisateur existant
        3. Rate limiting
        4. Envoi OTP via Didit
        5. Création de session
        """
        # Log initial de la requête
        logger.info(
            "phone_auth_request",
            ip=auth_utils.get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:100]
        )

        # 1. Validation des données d'entrée
        serializer = PhoneAuthSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("phone_auth_validation_failed", errors=serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Récupération des données validées
        full_phone_number = serializer.validated_data['phone_number']
        country_code = serializer.validated_data['country_code']

        # 2. Vérification de l'utilisateur existant
        try:
            user = User.objects.get(full_phone_number=full_phone_number)
            action = 'login'
            
            # Vérification du statut du compte
            if not user.is_active:
                logger.warning(
                    "inactive_account_attempt", 
                    phone_number=auth_utils.mask_phone(full_phone_number)
                )
                return Response({
                    "error": "Ce compte a été désactivé",
                    "code": "account_disabled"
                }, status=status.HTTP_403_FORBIDDEN)
                
        except User.DoesNotExist:
            user = None
            action = 'register'

        # 3. Rate limiting par numéro de téléphone
        if auth_utils.is_rate_limited(f"phone_{full_phone_number}", limit=3, window_seconds=300):
            logger.warning(
                "phone_rate_limited", 
                phone_number=auth_utils.mask_phone(full_phone_number)
            )
            return Response({
                "error": "Trop de tentatives récentes pour ce numéro",
                "code": "rate_limited",
                "retry_after": 300
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # 4. Rate limiting par IP
        client_ip = auth_utils.get_client_ip(request)
        if client_ip and auth_utils.is_rate_limited(f"ip_{client_ip}", limit=10, window_seconds=3600):
            logger.warning("ip_rate_limited", ip=client_ip)
            return Response({
                "error": "Trop de tentatives depuis cette adresse IP",
                "code": "ip_rate_limited",
                "retry_after": 3600
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # 5. Préparation des métadonnées pour Didit
        request_meta = auth_utils.extract_request_metadata(request)
        vendor_data = str(user.id) if user else None

        # 6. Envoi du code OTP via Didit
        result = didit_service.send_verification_code(
            phone_number=full_phone_number,
            request_meta=request_meta,
            vendor_data=vendor_data
        )

        if not result["success"]:
            logger.warning(
                "didit_send_failed",
                phone_number=auth_utils.mask_phone(full_phone_number),
                reason=result.get("reason"),
                message=result.get("message")
            )
            
            # Enregistrement de la tentative échouée
            auth_utils.is_rate_limited(f"phone_{full_phone_number}", limit=3, window_seconds=300)
            
            return Response({
                "error": result.get("message", "Échec d'envoi du code"),
                "code": result.get("reason", "send_failed"),
            }, status=status.HTTP_400_BAD_REQUEST)

        # 7. Création de la session d'authentification
        session_key = auth_utils.generate_session_key("auth")
        
        session_data = {
            "country_code": country_code,
            "action": action,
            "user_id": str(user.id) if user else None,
            "user_exists": user is not None,
            "request_id": result["request_id"],
            "request_meta": request_meta,
        }
        
        auth_utils.create_auth_session(session_key, full_phone_number, **session_data)

        # 8. Log du succès
        logger.info(
            "phone_auth_success",
            action=action,
            user_exists=user is not None,
            session_key=session_key[:8] + "...",
            phone_number=auth_utils.mask_phone(full_phone_number)
        )

        # 9. Préparation de la réponse
        response_data = self._prepare_auth_response(
            full_phone_number=full_phone_number,
            action=action,
            user=user,
            session_key=session_key,
            request_id=result["request_id"],
            didit_result=result
        )

        return Response(response_data, status=status.HTTP_200_OK)

    def _prepare_auth_response(self, full_phone_number, action, user, session_key, request_id, didit_result):
        """
        Prépare la réponse structurée après l'envoi réussi du code OTP.
        
        Args:
            full_phone_number: Numéro en E.164
            action: 'login' ou 'register'
            user: Objet User ou None
            session_key: Clé de session générée
            request_id: ID de la requête Didit
            didit_result: Résultat de l'appel Didit
        
        Returns:
            dict: Réponse formatée pour le frontend
        """
        # Masquage du numéro pour la réponse
        masked_phone = auth_utils.mask_phone(full_phone_number)
        
        # Construction de la réponse de base
        response_data = {
            "success": True,
            "action": action,
            "message": didit_result.get("message", "Code envoyé avec succès"),
            "session_key": session_key,
            "request_id": request_id,
            "phone_number": masked_phone,
            "phone_last_digits": full_phone_number[-2:],  # Pour confirmation visuelle
            "user_exists": user is not None,
            "expires_in": 300,  # 5 minutes en secondes
            "metadata": {
                "code_size": 6,
                "code_format": "numeric",
                "channel": "sms",
                "max_attempts": 3,
                "resend_allowed_after": 60,  # Peut renvoyer après 60s
            }
        }

        # Ajout des informations utilisateur si existant
        if user:
            response_data["user"] = {
                "id": str(user.id),
                "kyc_status": user.kyc_status,
                "phone_verified": user.phone_verified,
                "has_profile": bool(user.first_name and user.last_name)
            }

        return response_data 
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.utils import timezone
from django.core.cache import cache
from ..models import User
from ..Services.OTP_services import didit_service
from ..utils import auth_utils
import structlog

logger = structlog.get_logger(__name__)


class VerifyOTPView(APIView):
    """
    Vue pour la vérification du code OTP
    POST /api/auth/verify/
    """
    permission_classes = [AllowAny]

    def post(self, request):
        """
        Vérifie un code OTP et authentifie l'utilisateur.
        
        Flow:
        1. Validation des données
        2. Vérification de la session (si fournie)
        3. Appel à Didit pour vérification OTP
        4. Gestion succès/échec
        5. Création ou récupération de l'utilisateur
        6. Mise à jour utilisateur + session
        7. Génération des tokens JWT
        8. Réponse complète
        """
        serializer = VerifyOTPSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("verify_otp_validation_failed", errors=serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        full_phone_number = serializer.validated_data['phone_number']
        code = serializer.validated_data['code']
        session_key = serializer.validated_data.get('session_key')

        # 1. Vérification de la session (si fournie)
        session_data = None
        if session_key:
            session_data = cache.get(session_key)
            if not session_data:
                logger.warning("session_not_found", session_key=session_key)
                return Response({
                    "error": "Session expirée ou invalide",
                    "code": "session_expired"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Vérification de cohérence (numéro téléphone)
            if session_data.get('full_phone_number') != full_phone_number:
                logger.warning(
                    "session_mismatch",
                    session_phone=session_data.get('full_phone_number'),
                    provided_phone=full_phone_number
                )
                return Response({
                    "error": "Incohérence de session",
                    "code": "session_mismatch"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Limite de tentatives
            if session_data.get('attempts', 0) >= 3:
                return Response({
                    "error": "Trop de tentatives échouées",
                    "code": "max_attempts_exceeded",
                    "retry_after": 300
                }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # 2. Vérification OTP via Didit
        request_id = session_data.get('request_id') if session_data else None
        verify_result = didit_service.verify_code(full_phone_number, code, request_id)

        logger.info(
            "verify_otp_attempt",
            phone_number=auth_utils.mask_phone(full_phone_number),
            success=verify_result.get("success", False),
            verified=verify_result.get("verified", False)
        )

        # 3. Gestion des échecs
        if not verify_result.get("success", False):
            if session_data:
                auth_utils.update_session_attempt(session_key)
            return Response({
                "error": verify_result.get("message", "Échec de la vérification"),
                "code": "verification_failed"
            }, status=status.HTTP_400_BAD_REQUEST)

        if not verify_result.get("verified", False):
            if session_data:
                auth_utils.update_session_attempt(session_key)
            
            remaining = 3 - (session_data.get('attempts', 0) if session_data else 1)
            return Response({
                "error": "Code de vérification invalide",
                "code": "invalid_otp",
                "remaining_attempts": max(0, remaining)
            }, status=status.HTTP_400_BAD_REQUEST)

        # === SUCCÈS OTP ===
        phone_details = verify_result.get("phone_details", {})
        didit_status = verify_result.get("status")

        # 4. Sécurité : blocage numéros frauduleux
        if phone_details.get("is_disposable") or phone_details.get("is_virtual"):
            logger.warning(
                "blocked_fraudulent_phone",
                phone_number=auth_utils.mask_phone(full_phone_number),
                is_disposable=phone_details.get("is_disposable"),
                is_voip=phone_details.get("is_virtual")
            )
            return Response({
                "error": "Les numéros temporaires ou virtuels ne sont pas autorisés",
                "code": "fraudulent_phone"
            }, status=status.HTTP_403_FORBIDDEN)

        # 5. Déduction de l'action si pas dans la session
        action = session_data.get('action') if session_data else None
        if not action:
            action = 'login' if User.objects.filter(full_phone_number=full_phone_number).exists() else 'register'

        country_code = session_data.get('country_code') if session_data else phone_details.get("country_code", "+33")

        # 6. Gestion utilisateur
        try:
            user = User.objects.get(full_phone_number=full_phone_number)
            logger.debug("user_found", user_id=str(user.id))
        except User.DoesNotExist:
            if action == 'register':
                # Création propre sans passer full_phone_number (le manager s'en charge)
                national_number = full_phone_number.replace(country_code, "").strip()
                if national_number.startswith('0'):
                    national_number = national_number[1:]
                
                user = User.objects.create_user(
                    phone_number=national_number,
                    country_code=country_code
                )
                logger.info("user_created_via_otp", user_id=str(user.id))
            else:
                return Response({
                    "error": "Utilisateur introuvable",
                    "code": "user_not_found"
                }, status=status.HTTP_404_NOT_FOUND)

        # 7. Mise à jour utilisateur avec données Didit
        user.carrier = phone_details.get("carrier", "")
        user.is_disposable = phone_details.get("is_disposable", False)
        user.is_voip = phone_details.get("is_virtual", False)
        user.phone_verified = True
        user.phone_verified_at = timezone.now()
        user.last_login = timezone.now()
        user.save()
            
        # 8. Mise à jour session (prolongation)
        if session_key and session_data:
            session_data['user_id'] = str(user.id)
            session_data['verified'] = True
            session_data['auth_completed_at'] = timezone.now().isoformat()
            cache.set(session_key, session_data, timeout=600)  # 10 min supplémentaires

        # 9. Tokens JWT
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        tokens = {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }

        # 10. Sérialisation utilisateur
        from ..Serializers.OTP_serializers import UserSerializer
        user_serializer = UserSerializer(user)

        # 11. Réponse finale
        response_data = {
            "success": True,
            "action": action,
            "message": "Authentification réussie",
            "user": user_serializer.data,
            "auth": {
                "access_token": tokens['access'],
                "refresh_token": tokens['refresh'],
                "expires_in": 3600,  # 1 heure
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
                "verification_method": phone_details.get("verification_method", "sms"),
                "session_key": session_key if session_key else None
            }
        }

        logger.info(
            "verify_otp_success",
            action=action,
            user_id=str(user.id),
            phone_verified=True
        )

        return Response(response_data, status=status.HTTP_200_OK)
class ResendOTPView(APIView):
    """
    Vue pour renvoyer un code OTP.
    Note: Didit ne propose pas d'endpoint resend, donc on renvoie un nouveau code.
    POST /api/auth/resend/
    """
    permission_classes = [AllowAny]

    def post(self, request):
        """
        Renvoie un nouveau code OTP (nouvelle requête Didit).
        
        Flow:
        1. Validation de la session
        2. Vérification du rate limiting
        3. Nouvel envoi via Didit
        4. Mise à jour de la session
        """
        from ..Serializers.OTP_serializers import ResendOTPSerializer
        
        serializer = ResendOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        session_key = serializer.validated_data['session_key']
        session_data = cache.get(session_key)

        if not session_data:
            return Response({
                "error": "Session expirée",
                "code": "session_expired"
            }, status=status.HTTP_400_BAD_REQUEST)

        full_phone_number = session_data['full_phone_number']
        request_meta = session_data.get('request_meta', {})
        user_id = session_data.get('user_id')
        
        # Vérification du rate limiting pour le renvoi
        if auth_utils.is_rate_limited(f"resend_{full_phone_number}", limit=3, window_seconds=60):
            logger.warning(
                "resend_rate_limited",
                phone_number=auth_utils.mask_phone(full_phone_number)
            )
            return Response({
                "error": "Veuillez patienter avant de renvoyer un nouveau code",
                "code": "resend_rate_limited",
                "retry_after": 60
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Envoi d'un NOUVEAU code (pas de resend chez Didit)
        result = didit_service.send_verification_code(
            phone_number=full_phone_number,
            request_meta=request_meta,
            vendor_data=user_id
        )

        if not result["success"]:
            logger.warning(
                "resend_failed",
                phone_number=auth_utils.mask_phone(full_phone_number),
                reason=result.get("reason")
            )
            return Response({
                "error": result["message"],
                "code": "resend_failed"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Mise à jour de la session avec le nouveau request_id
        session_data["request_id"] = result["request_id"]
        session_data["resent_count"] = session_data.get("resent_count", 0) + 1
        session_data["last_resend_at"] = timezone.now().isoformat()
        
        # Réinitialiser le timeout de la session
        cache.set(session_key, session_data, timeout=300)

        logger.info(
            "otp_resent",
            phone_number=auth_utils.mask_phone(full_phone_number),
            resent_count=session_data["resent_count"],
            new_request_id=result["request_id"][:20]
        )

        return Response({
            "success": True,
            "message": "Nouveau code envoyé avec succès",
            "request_id": result["request_id"],
            "session_key": session_key,
            "expires_in": 300,
            "metadata": {
                "resent_count": session_data["resent_count"],
                "max_resends": 3
            }
        })    
class AuthStatusView(APIView):
    """
    Vue pour vérifier le statut d'une session d'authentification
    GET /api/auth/status/?session_key=xxx
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """
        Vérifie si une session est toujours valide et retourne son état.
        
        Utilisations:
        - Vérifier si une session OTP est encore valide
        - Récupérer les informations de session pour le frontend
        - Vérifier si l'authentification est complète
        """
        session_key = request.query_params.get('session_key')
        
        if not session_key:
            logger.debug("status_check_no_session")
            return Response({
                "authenticated": False,
                "message": "Session non fournie",
                "code": "no_session_key"
            })

        session_data = cache.get(session_key)
        
        if not session_data:
            logger.debug("status_check_expired", session_key=session_key[:8] + "...")
            return Response({
                "authenticated": False,
                "message": "Session expirée ou invalide",
                "code": "session_expired"
            })

        # Récupération des informations de session
        full_phone_number = session_data.get('full_phone_number')
        action = session_data.get('action')
        user_id = session_data.get('user_id')
        verified = session_data.get('verified', False)
        attempts = session_data.get('attempts', 0)
        
        # Calcul du temps restant manuellement (compatible LocMemCache)
        expires_at_str = session_data.get('expires_at')
        expires_in = self._calculate_time_remaining(expires_at_str)
        created_at = session_data.get('created_at')
        
        # Récupération de l'utilisateur si ID disponible
        user = None
        user_data = None
        if user_id:
            try:
                user = User.objects.get(id=user_id, is_active=True)
                from ..Serializers.OTP_serializers import UserSerializer
                user_data = UserSerializer(user).data
            except User.DoesNotExist:
                logger.warning(
                    "status_user_not_found",
                    session_key=session_key[:8] + "...",
                    user_id=user_id
                )
                user = None

        response_data = {
            "authenticated": True,
            "session": {
                "key": session_key[:8] + "...",  # Masqué pour la sécurité
                "phone_number": auth_utils.mask_phone(full_phone_number) if full_phone_number else None,
                "phone_last_digits": full_phone_number[-2:] if full_phone_number else None,
                "action": action,
                "user_exists": user is not None,
                "verified": verified,
                "attempts": attempts,
                "created_at": created_at,
                "expires_at": expires_at_str,
                "expires_in": expires_in,
                "is_active": expires_in > 0,
                "last_attempt": session_data.get('last_attempt')
            },
            "user": user_data,
            "next_steps": self._get_next_steps(session_data, user)
        }

        # Ajouter des métadonnées supplémentaires si la session est vérifiée
        if verified:
            response_data["metadata"] = {
                "auth_completed_at": session_data.get('auth_completed_at'),
                "remaining_validity": max(0, expires_in),
                "request_id": session_data.get('request_id')
            }

        logger.debug(
            "status_check_success",
            session_key=session_key[:8] + "...",
            verified=verified,
            expires_in=expires_in,
            action=action
        )

        return Response(response_data)

    def _calculate_time_remaining(self, expires_at_str):
        """
        Calcule le temps restant avant expiration.
        Compatible avec tous les backends de cache (LocMemCache, Redis, etc.)
        
        Args:
            expires_at_str: Chaîne ISO format de la date d'expiration
            
        Returns:
            int: Nombre de secondes restantes (0 si expiré)
        """
        if not expires_at_str:
            return 0
        
        try:
            from django.utils import timezone
            from datetime import datetime
            
            # Convertir la string ISO en datetime
            if 'Z' in expires_at_str:
                expires_at_str = expires_at_str.replace('Z', '+00:00')
            
            expires_at = datetime.fromisoformat(expires_at_str)
            
            # S'assurer que c'est un datetime conscient (timezone aware)
            if timezone.is_naive(expires_at):
                expires_at = timezone.make_aware(expires_at)
            
            now = timezone.now()
            time_remaining = (expires_at - now).total_seconds()
            
            # Retourner 0 si négatif (déjà expiré)
            return max(0, int(time_remaining))
            
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning(
                "time_remaining_calculation_error",
                error=str(e),
                expires_at_str=expires_at_str
            )
            return 0

    def _get_next_steps(self, session_data, user):
        """
        Détermine les prochaines étapes pour l'utilisateur.
        
        Args:
            session_data: Données de la session
            user: Objet User ou None
            
        Returns:
            list: Liste des prochaines actions recommandées
        """
        next_steps = []
        
        # Vérifier si c'est une session de suppression
        if session_data.get('action') == 'delete_account':
            if not session_data.get('verified'):
                next_steps.append("enter_delete_code")
            return next_steps
        
        # Session OTP standard
        if not session_data.get('verified'):
            # Session OTP non vérifiée
            next_steps.append("verify_otp")
            
            if session_data.get('attempts', 0) >= 2:
                next_steps.append("resend_otp")
            elif session_data.get('attempts', 0) == 1:
                next_steps.append("careful_input")
        
        elif user:
            # Utilisateur authentifié
            if not user.phone_verified:
                next_steps.append("complete_phone_verification")
            
            if user.kyc_status == 'unverified':
                next_steps.append("complete_kyc")
            elif user.kyc_status == 'rejected':
                if user.kyc_retry_count < 3:
                    next_steps.append("retry_kyc")
                else:
                    next_steps.append("contact_support")
            elif user.kyc_status == 'pending':
                next_steps.append("wait_kyc_approval")
            
            if not user.first_name or not user.last_name:
                next_steps.append("complete_profile")
            
            if not user.email:
                next_steps.append("add_email")
        
        # Ajouter des warnings si nécessaire
        if session_data.get('attempts', 0) == 2:
            next_steps.append("last_attempt_warning")
        
        if session_data.get('resent_count', 0) >= 2:
            next_steps.append("max_resend_warning")
        
        return next_steps
class ProfileView(APIView):
    """
    GET /api/profile/
    
    Retourne le profil complet de l'utilisateur connecté
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Récupère et retourne le profil de l'utilisateur authentifié.
        
        Inclut:
        - Informations de base
        - Statut de vérification
        - État KYC
        - Prochaines étapes recommandées
        """
        user = request.user
        
        # Vérifier que l'utilisateur a bien vérifié son téléphone
        if not user.phone_verified:
            return Response({
                "success": False,
                "error": "Votre numéro de téléphone n'est pas vérifié",
                "code": "phone_not_verified",
                "next_step": "verify_phone"
            }, status=status.HTTP_403_FORBIDDEN)

        # Sérialisation du profil
        from ..Serializers.profile import ProfileSerializer
        serializer = ProfileSerializer(user)
        profile_data = serializer.data
        
        # Ajout d'informations contextuelles
        profile_data['completion_percentage'] = self._calculate_profile_completion(user)
        profile_data['next_steps'] = self._get_profile_next_steps(user)
        profile_data['verification_status'] = {
            'phone': {
                'verified': user.phone_verified,
                'verified_at': user.phone_verified_at,
                'carrier': user.carrier
            },
            'identity': {
                'status': user.kyc_status,
                'verified_at': user.kyc_verified_at,
                'retry_count': user.kyc_retry_count
            }
        }

        logger.info("profile_viewed", user_id=str(user.id))

        return Response({
            "success": True,
            "profile": profile_data,
            "metadata": {
                "retrieved_at": timezone.now().isoformat(),
                "requires_kyc": user.kyc_status != 'verified'
            }
        }, status=status.HTTP_200_OK)

    def _calculate_profile_completion(self, user):
        """
        Calcule le pourcentage de complétion du profil.
        """
        total_fields = 8
        completed_fields = 0
        
        # Champs obligatoires
        if user.phone_verified:
            completed_fields += 2  # Téléphone vérifié + numéro
        
        if user.first_name:
            completed_fields += 1
        
        if user.last_name:
            completed_fields += 1
        
        if user.email:
            completed_fields += 1
        
        if user.kyc_status == 'verified':
            completed_fields += 2  # KYC + date de naissance
        
        # Champs bonus
        if user.kyc_document_number:
            completed_fields += 0.5
        
        if user.kyc_address:
            completed_fields += 0.5
        
        return min(100, int((completed_fields / total_fields) * 100))

    def _get_profile_next_steps(self, user):
        """
        Détermine les prochaines étapes pour compléter le profil.
        """
        next_steps = []
        
        if not user.email:
            next_steps.append({
                "action": "add_email",
                "priority": "high",
                "message": "Ajoutez votre adresse email"
            })
        
        if not user.first_name or not user.last_name:
            next_steps.append({
                "action": "complete_name",
                "priority": "high",
                "message": "Complétez votre nom et prénom"
            })
        
        if user.kyc_status == 'unverified':
            next_steps.append({
                "action": "verify_identity",
                "priority": "medium",
                "message": "Vérifiez votre identité (KYC)"
            })
        elif user.kyc_status == 'rejected':
            if user.kyc_retry_count < 3:
                next_steps.append({
                    "action": "retry_kyc",
                    "priority": "high",
                    "message": "Votre vérification a été rejetée, réessayez"
                })
            else:
                next_steps.append({
                    "action": "contact_support",
                    "priority": "critical",
                    "message": "Contactez le support pour votre vérification"
                })
        
        return next_steps