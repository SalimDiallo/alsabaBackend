from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import login
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta
import random
from .models import User, KYCDocument
from django.contrib.auth import logout
from .serializers import (
    PhoneNumberSerializer,
    UserProfileSerializer,
    KYCVerificationSerializer,
    AccountDeletionSerializer,
    KYCDocumentSerializer,
    PhoneAuthSerializer,
    OTPSerializer
)
from .services import KYCService
from .utils import create_otp_for_user, send_sms_otp, validate_otp
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
        
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.utils import timezone
from django.core.cache import cache

from .serializers import PhoneAuthSerializer, DiditVerifySerializer
from .services import DiditPhoneService
class CheckPhoneNumberView(APIView):
    """Vérifie si un numéro de téléphone existe déjà"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = PhoneNumberSerializer(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']
            country_code = serializer.validated_data['country_code']
            
            # Vérifier si l'utilisateur existe déjà
            try:
                user = User.objects.get(phone_number=phone_number)
                return Response({
                    "exists": True,
                    "message": "Numéro déjà enregistré",
                    "user_id": str(user.id)
                }, status=status.HTTP_200_OK)
            except User.DoesNotExist:
                return Response({
                    "exists": False,
                    "message": "Numéro disponible"
                }, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserProfileView(APIView):
    """Récupérer et mettre à jour le profil utilisateur"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Récupérer le profil COMPLET de l'utilisateur connecté
        Inclut les stats et informations KYC
        """
        user = request.user
        
        # Données de base du profil
        serializer = UserProfileSerializer(user)
        profile_data = serializer.data
        
        # Ajouter des statistiques
        from django.utils import timezone
        from datetime import timedelta
        
        stats = {
            "account_age_days": (timezone.now() - user.date_joined).days,
            "last_login": user.last_login,
            "days_since_last_login": (
                (timezone.now() - user.last_login).days 
                if user.last_login else None
            ),
            "kyc_documents_count": user.kyc_documents.count(),
            "has_pending_kyc": user.kyc_status == 'pending',
            "is_kyc_verified": user.is_verified,
            "kyc_submitted_date": user.kyc_submitted_at,
            "kyc_verified_date": user.kyc_verified_at,
        }
        
        # Information pour le frontend
        frontend_info = {
            "next_steps": self._get_next_steps(user),
            "completion_percentage": self._calculate_profile_completion(user),
            "required_actions": self._get_required_actions(user),
        }
        
        return Response({
            "profile": profile_data,
            "stats": stats,
            "frontend_info": frontend_info,
            "last_updated": timezone.now(),
        }, status=status.HTTP_200_OK)
    
    def patch(self, request):
        """
        Mettre à jour partiellement le profil
        Avec validation améliorée et logs
        """
        user = request.user
        
        # Log de la tentative de modification
        from django.contrib.auth.models import update_last_login
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"User {user.id} attempting profile update with data: {request.data}")
        
        # Validation des données avant sérialisation
        if 'email' in request.data:
            email = request.data['email']
            if email and User.objects.filter(email=email).exclude(id=user.id).exists():
                return Response({
                    "error": "Cet email est déjà utilisé par un autre compte"
                }, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = UserProfileSerializer(
            user, 
            data=request.data, 
            partial=True
        )
        
        if serializer.is_valid():
            # Sauvegarder les modifications
            serializer.save()
            
            # Mettre à jour le timestamp de modification
            user.profile_updated_at = timezone.now()
            user.save(update_fields=['profile_updated_at'])
            
            logger.info(f"User {user.id} profile updated successfully")
            
            # Retourner la réponse enrichie
            return Response({
                "message": "✅ Profil mis à jour avec succès",
                "user": serializer.data,
                "updated_at": user.profile_updated_at,
                "changes": self._get_changed_fields(user, request.data),
                "next_recommended_step": self._get_next_steps(user)[0] if self._get_next_steps(user) else None
            }, status=status.HTTP_200_OK)
        
        # Log des erreurs de validation
        logger.warning(f"User {user.id} profile update failed: {serializer.errors}")
        
        return Response({
            "error": "Validation error",
            "details": serializer.errors,
            "suggestions": self._get_validation_suggestions(serializer.errors)
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # ========== MÉTHODES PRIVÉES UTILITAIRES ==========
    
    def _get_next_steps(self, user):
        """
        Détermine les prochaines étapes recommandées pour l'utilisateur
        """
        steps = []
        
        if not user.first_name or not user.last_name:
            steps.append("complete_name")
        
        if not user.email:
            steps.append("add_email")
        
        if user.kyc_status == 'unverified':
            steps.append("complete_kyc")
        elif user.kyc_status == 'pending':
            steps.append("wait_kyc_verification")
        elif user.kyc_status == 'rejected':
            steps.append("resubmit_kyc")
        
        if not user.kyc_documents.exists():
            steps.append("upload_documents")
        
        return steps
    
    def _calculate_profile_completion(self, user):
        """
        Calcule le pourcentage de complétion du profil
        """
        total_points = 0
        completed_points = 0
        
        # Nom complet (20 points)
        total_points += 20
        if user.first_name and user.last_name:
            completed_points += 20
        
        # Email (15 points)
        total_points += 15
        if user.email:
            completed_points += 15
        
        # KYC vérifié (50 points)
        total_points += 50
        if user.is_verified:
            completed_points += 50
        
        # Documents uploadés (15 points)
        total_points += 15
        if user.kyc_documents.exists():
            completed_points += 15
        
        return int((completed_points / total_points) * 100) if total_points > 0 else 0
    
    def _get_required_actions(self, user):
        """
        Liste les actions requises (obligatoires)
        """
        actions = []
        
        if user.kyc_status == 'unverified':
            actions.append({
                "action": "kyc_verification",
                "priority": "high",
                "message": "La vérification KYC est requise pour effectuer des transactions"
            })
        
        return actions
    
    def _get_changed_fields(self, user, request_data):
        """
        Identifie quels champs ont été modifiés
        """
        changed = []
        for field in ['first_name', 'last_name', 'email']:
            if field in request_data:
                changed.append(field)
        return changed
    
    def _get_validation_suggestions(self, errors):
        """
        Donne des suggestions pour corriger les erreurs de validation
        """
        suggestions = {}
        
        if 'email' in errors:
            if 'unique' in str(errors['email']):
                suggestions['email'] = "Cet email est déjà utilisé. Essayez un autre email."
            elif 'invalid' in str(errors['email']):
                suggestions['email'] = "Format d'email invalide. Exemple: utilisateur@email.com"
        
        if 'first_name' in errors or 'last_name' in errors:
            suggestions['name'] = "Les noms doivent contenir uniquement des lettres"
        
        return suggestions
    
    # Optionnel: Ajouter PUT pour mise à jour complète
    def put(self, request):
        """
        Mise à jour COMPLÈTE du profil (tous les champs requis)
        """
        return Response({
            "message": "Utilisez PATCH pour les mises à jour partielles",
            "note": "PUT nécessite tous les champs, PATCH permet des mises à jour partielles"
        }, status=status.HTTP_405_METHOD_NOT_ALLOWED)

class DeleteAccountView(APIView):
    """Supprimer le compte utilisateur"""
    permission_classes = [IsAuthenticated]
    
    def delete(self, request):
        serializer = AccountDeletionSerializer(data=request.data)
        
        if serializer.is_valid():
            user = request.user
            
            # Soft delete - on désactive le compte sans le supprimer
            user.is_active = False
            user.save()
            
            # Optionnel : Déconnecter l'utilisateur de la session Django
            from django.contrib.auth import logout
            logout(request)
            
            return Response({
                "message": "Compte désactivé avec succès",
                "note": "Votre compte a été désactivé. Vous pourrez le réactiver en contactant le support."
            }, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LogoutView(APIView):
    """Déconnexion simple"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        logout(request)
        return Response({
            "message": "Déconnecté avec succès"
        }, status=status.HTTP_200_OK)
# POUR L'AUTHENTIFICATION PAR TÉLÉPHONE ET OTP
           
# class PhoneAuthView(APIView):
#     """Endpoint unifié pour login/register par téléphone"""
#     permission_classes = [AllowAny]
    
#     def post(self, request):
#         serializer = PhoneAuthSerializer(data=request.data)
#         if not serializer.is_valid():
#             return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
#         phone_number = serializer.validated_data['phone_number']
#         country_code = serializer.validated_data['country_code']
        
#         # Vérifier si l'utilisateur existe déjà
#         try:
#             user = User.objects.get(phone_number=phone_number)
#             action = 'login'
            
#             if not user.is_active:
#                 return Response({
#                     "error": "Ce compte a été désactivé"
#                 }, status=status.HTTP_400_BAD_REQUEST)
                
#         except User.DoesNotExist:
#             # Créer un nouvel utilisateur
#             user = User.objects.create_user(
#                 phone_number=phone_number,
#                 country_code=country_code,
#             )
#             action = 'register'
        
#         # Créer un OTP pour l'utilisateur
#         otp_code = create_otp_for_user(user, expires_in_minutes=10)
        
#         # Simuler l'envoi SMS (à remplacer en production)
#         sms_result = send_sms_otp(
#             phone_number=user.full_phone,
#             otp_code=otp_code,
#             provider="TwilioSandBox"
#         )
        
#         # NE PAS générer de tokens ici - seulement après vérification OTP
#         # NE PAS mettre à jour last_login ici - seulement après vérification OTP
        
#         return Response({
#             "action": action,
#             "message": f"{'Connexion' if action == 'login' else 'Inscription'} initiée",
#             "phone_number": phone_number,
#             "country_code": country_code,
#             "otp_sent": True,
#             "sms_simulation": sms_result,  # Retirer en production
            
#             # INFOS UTILISATEUR SANS TOKENS
#             "user_info": {
#                 "id": str(user.id),
#                 "kyc_status": user.kyc_status,
#                 "is_verified": user.is_verified,
#                 "kyc_status_display": user.get_kyc_status_display(),
#                 "has_kyc_documents": user.kyc_documents.exists()
#             },
            
#             "kyc_info": {
#                 "status": user.kyc_status,
#                 "is_verified": user.is_verified,
#                 "required": True,
#                 "next_step": "verify-otp"  # Toujours "verify-otp"
#             },
            
#             "user_id": str(user.id),
#             "expires_in": "10 minutes",
#             "note": "Utilisez /verify-otp/ avec le code reçu pour obtenir vos tokens d'accès"
#         }, status=status.HTTP_200_OK)
# class VerifyOTPView(APIView):
#     """Vérifier l'OTP et authentifier l'utilisateur"""
#     permission_classes = [AllowAny]
    
#     def post(self, request):
#         serializer = OTPSerializer(data=request.data)
#         if not serializer.is_valid():
#             return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
#         phone_number = serializer.validated_data['phone_number']
#         otp_code = serializer.validated_data['otp']
        
#         # Valider l'OTP
#         success, message, user = validate_otp(phone_number, otp_code)
        
#         if not success:
#             return Response({
#                 "error": message
#             }, status=status.HTTP_400_BAD_REQUEST)
        
#         # Mettre à jour last_login
#         user.last_login = timezone.now()
#         user.save()
        
#         return Response({
#             "message": "Authentification réussie",
#             "user": {
#                 "id": str(user.id),
#                 "phone_number": user.phone_number,
#                 "country_code": user.country_code,
#                 "kyc_status": user.kyc_status,
#                 "is_verified": user.is_verified,
#                 "kyc_status_display": user.get_kyc_status_display(),
#                 "has_kyc_documents": user.kyc_documents.exists()
#             },
#             "otp_verified": True,
#             "kyc_info": {
#                 "status": user.kyc_status,
#                 "is_verified": user.is_verified,
#                 "required": True,
#                 "next_step": "complete-profile" if user.kyc_status == "unverified" else "ready"
#             }
#         }, status=status.HTTP_200_OK)
#Pour le debug des OTP
class DebugOTPView(APIView):
    pass
#     """
#     Vue de debug pour voir les OTP actifs
#     À désactiver en production !
#     """
#     permission_classes = [AllowAny]  # En production : IsAdminUser
    
#     def get(self, request):
#         from .utils import get_active_otps_count
        
#         active_otps = OTPCode.objects.filter(
#             used=False,
#             expires_at__gt=timezone.now()
#         ).select_related('user')
        
#         data = []
#         for otp in active_otps:
#             data.append({
#                 'user': {
#                     'id': str(otp.user.id),
#                     'phone': otp.user.phone_number,
#                     'full_phone': otp.user.full_phone
#                 },
#                 'code': otp.code,
#                 'created': otp.created_at,
#                 'expires': otp.expires_at,
#                 'remaining_minutes': max(0, (otp.expires_at - timezone.now()).seconds // 60),
#                 'is_valid': otp.expires_at > timezone.now() and not otp.used
#             })
        
#         return Response({
#             "count": len(data),
#             "active_otps": data,
#             "total_active": get_active_otps_count(),
#             "timestamp": timezone.now()
#         })
@method_decorator(csrf_exempt, name="dispatch")
class DiditWebhookView(APIView):
    def post(self, request):
        # TODO: Valider la signature Didit (header X-Didit-Signature)
        # Exemple avec HMAC :
        # import hmac, hashlib
        # signature = request.headers.get("X-Didit-Signature")
        # computed = hmac.new(settings.DIDIT_WEBHOOK_SECRET.encode(), request.body, hashlib.sha256).hexdigest()
        # if not hmac.compare_digest(signature, computed):
        #     return HttpResponse("Signature invalide", status=401)

        try:
            payload = request.data
            message, code = KYCService.handle_didit_webhook(payload)
            return Response(message, status=code)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
class KYCVerificationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        documents = KYCDocument.objects.filter(user=request.user)
        serializer = KYCDocumentSerializer(documents, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        user = request.user
        document_type = request.data.get("document_type")

        if not document_type:
            return Response({"error": "Type de document requis"}, status=status.HTTP_400_BAD_REQUEST)

        # Vérifications préalables
        if user.kyc_status == "verified":
            return Response({"error": "Compte déjà vérifié"}, status=status.HTTP_400_BAD_REQUEST)
        if user.kyc_status == "pending":
            return Response({"error": "Demande déjà en cours"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 1. Créer la session Didit
            session_data = KYCService.create_didit_session(document_type, user)

            # 2. Créer le document local
            document = KYCService.create_document(
                user=user,
                document_type=document_type,
                session_id=session_data["session_id"],
            )

            # 3. Mettre à jour le statut utilisateur
            KYCService.update_user_status(user, "pending")

            return Response({
                "message": "Session KYC créée avec succès",
                "document_id": document.id,
                "document_type": document_type,
                "session_id": session_data["session_id"],
                "session_url": session_data["session_url"],  # À utiliser dans le frontend
                "kyc_status": user.kyc_status,
                "submitted_at": user.kyc_submitted_at,
            }, status=status.HTTP_201_CREATED)

        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
class KYCStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        documents_count = KYCDocument.objects.filter(user=user).count()

        # Optionnel : rafraîchir le statut si pending
        if user.kyc_status == "pending":
            latest_doc = KYCDocument.objects.filter(user=user).order_by("-created_at").first()
            if latest_doc and latest_doc.session_id:
                # Ici tu peux appeler l'API Didit pour vérifier (mais webhook est préférable)
                pass

        return Response({
            "kyc_status": user.kyc_status,
            "is_verified": user.is_verified,
            "kyc_submitted_at": user.kyc_submitted_at,
            "kyc_verified_at": user.kyc_verified_at,
            "documents_count": documents_count,
        }, status=status.HTTP_200_OK)
#Configuraton OTP avec Didit
class PhoneAuthView(APIView):
    """Endpoint unifié pour login/register avec Didit"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = PhoneAuthSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        phone_number = serializer.validated_data['phone_number']
        
        # Vérifier si l'utilisateur existe déjà
        try:
            user = User.objects.get(phone_number=phone_number)
            action = 'login'
            
            if not user.is_active:
                return Response({
                    "error": "Ce compte a été désactivé"
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except User.DoesNotExist:
            # Créer un nouvel utilisateur
            user = User.objects.create_user(phone_number=phone_number)
            action = 'register'
        
        # Envoyer le code via Didit (Didit génère le code)
        service = DiditPhoneService()
        result = service.send_verification_code(
            phone_number=phone_number,
            vendor_user_id=str(user.id)
        )
        
        if not result["success"]:
            return Response({
                "error": result["message"]
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Stocker le session_uuid en cache pour l'utilisateur
        cache_key = f"didit_session:{user.id}"
        cache.set(cache_key, result["session_uuid"], timeout=300)  # 5 min comme Didit
        
        return Response({
            "action": action,
            "message": f"{'Connexion' if action == 'login' else 'Inscription'} initiée",
            "phone_number": phone_number,
            "otp_sent": True,
            "session_uuid": result["session_uuid"],  # Important pour la vérification
            "user_id": str(user.id),
            "expires_in": "5 minutes",  # Didit expire après 5 min
            "note": "Utilisez /verify-otp/ avec le code reçu par SMS"
        }, status=status.HTTP_200_OK)
class VerifyOTPView(APIView):
    """Vérifie le code via l'API Didit"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = DiditVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        user_id = serializer.validated_data['user_id']
        user_code = serializer.validated_data['otp']
        
        # Récupérer le session_uuid depuis le cache
        cache_key = f"didit_session:{user_id}"
        session_uuid = cache.get(cache_key)
        
        if not session_uuid:
            return Response({
                "error": "Session expirée ou invalide"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Vérifier le code avec Didit
        service = DiditPhoneService()
        verified, message = service.verify_code(session_uuid, user_code)
        
        if not verified:
            return Response({
                "error": message or "Code incorrect"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Récupérer l'utilisateur
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({
                "error": "Utilisateur non trouvé"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Mettre à jour last_login
        user.last_login = timezone.now()
        user.save()
        
        # Nettoyer le cache
        cache.delete(cache_key)
        
        return Response({
            "message": "Authentification réussie",
            "user": {
                "id": str(user.id),
                "phone_number": user.phone_number,
            },
            "otp_verified": True,
        }, status=status.HTTP_200_OK)