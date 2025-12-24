from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.utils import timezone
from django.core.cache import cache
import uuid

from ..Serializers.OTP_serializers import PhoneAuthSerializer, VerifyOTPSerializer, UserSerializer
from ..Services.OTP_services import didit_service
from ..models import User


class PhoneAuthView(APIView):
    """
    Endpoint: POST /api/auth/phone/
    
    Envoie un code de vérification via Didit.
    Détermine si c'est un register ou login.
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        # Validation des données
        serializer = PhoneAuthSerializer(data=request.data)
        if not serializer.is_valid():
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
                return Response({
                    "error": "Ce compte a été désactivé",
                    "code": "account_disabled"
                }, status=status.HTTP_403_FORBIDDEN)
                
        except User.DoesNotExist:
            # Pas encore d'utilisateur
            user = None
            action = 'register'
        
        # Préparer les données pour Didit
        vendor_data = str(user.id) if user else None
        
        # Extraire les métadonnées pour les signaux de fraude
        request_meta = {
            'REMOTE_ADDR': self._get_client_ip(request),
            'HTTP_USER_AGENT': request.META.get('HTTP_USER_AGENT', ''),
        }
        
        # Appel au service Didit
        result = didit_service.send_verification_code(
            phone_number=phone_number,
            request_meta=request_meta,
            vendor_data=vendor_data
        )
        
        # Gestion des réponses Didit
        if not result["success"]:
            return Response({
                "error": result["message"],
                "code": result["reason"],
                "status": result["status"]
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Stocker la session temporairement
        session_key = f"auth_session_{uuid.uuid4().hex[:16]}"
        session_data = {
            "phone_number": phone_number,
            "country_code": country_code,
            "action": action,
            "request_id": result["request_id"],  # ID de la requête Didit
            "user_id": str(user.id) if user else None,
            "created_at": timezone.now().isoformat(),
            "expires_at": (timezone.now() + timezone.timedelta(minutes=5)).isoformat()
        }
        
        # Stockage en cache pour 5 minutes (durée de validité du code)
        cache.set(session_key, session_data, timeout=300)
        
        # Réponse au client
        response_data = {
            "success": True,
            "action": action,
            "message": result["message"],
            "session_key": session_key,
            "request_id": result["request_id"],
            "phone_number": phone_number,
            "user_exists": user is not None,
            "expires_in": 300,  # secondes
            "metadata": {
                "code_size": 6,
                "channel": "sms"
            }
        }
        
        # Ajouter les infos utilisateur si login
        if user:
            response_data["user"] = {
                "id": str(user.id),
                "kyc_status": user.kyc_status,
                "is_verified": user.is_verified
            }
        
        return Response(response_data, status=status.HTTP_200_OK)
    
    def _get_client_ip(self, request):
        """Récupère l'IP réelle du client"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class VerifyOTPView(APIView):
    """
    Endpoint: POST /api/auth/verify/
    
    Vérifie le code OTP et authentifie l'utilisateur.
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        # Validation
        serializer = VerifyOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )
        
        phone_number = serializer.validated_data['phone_number']
        code = serializer.validated_data['code']
        request_id = serializer.validated_data['request_id']
        
        # Vérification avec Didit
        verify_result = didit_service.verify_code(request_id, code)
        
        if not verify_result["success"]:
            return Response({
                "error": verify_result["message"],
                "code": "verification_failed"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if not verify_result["verified"]:
            return Response({
                "error": "Code de vérification invalide",
                "code": "invalid_otp"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Rechercher la session par request_id
        # Note: Dans une vraie implémentation, il faudrait stocker
        # la session avec le request_id comme clé ou dans une base
        
        # Pour simplifier, on recherche l'utilisateur par phone
        try:
            user = User.objects.get(phone_number=phone_number)
            action = 'login'
        except User.DoesNotExist:
            # Création de l'utilisateur (register)
            # On a besoin du country_code, qui devrait être stocké
            # Pour l'exemple, on extrait du phone_number
            from phonenumbers import parse, format_number, PhoneNumberFormat
            parsed = parse(phone_number)
            country_code = '+' + str(parsed.country_code)
            
            user = User.objects.create_user(
                phone_number=phone_number,
                country_code=country_code,
                kyc_status='unverified',
                is_verified=False
            )
            user.set_unusable_password()
            user.save()
            action = 'register'
        
        # Mettre à jour last_login
        user.last_login = timezone.now()
        user.save()
        
        # Sérialiser la réponse
        user_serializer = UserSerializer(user)
        
        return Response({
            "success": True,
            "action": action,
            "message": "Authentification réussie",
            "user": user_serializer.data,
            "kyc_info": {
                "status": user.kyc_status,
                "is_verified": user.is_verified,
                "required": True,
                "next_step": "complete_profile" if user.kyc_status == "unverified" else "ready"
            },
            "otp_verified": True,
            "session": {
                "authenticated": True,
                "user_id": str(user.id)
            }
        }, status=status.HTTP_200_OK)


class AuthStatusView(APIView):
    """Vérifie le statut d'authentification"""
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
        
        return Response({
            "authenticated": True,
            "session": session_data,
            "expires_in": cache.ttl(session_key)
        })