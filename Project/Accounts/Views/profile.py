# apps/auth/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from ..Serializers.profile import ProfileSerializer
from django.utils import timezone
import structlog    
logger = structlog.get_logger(__name__)
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