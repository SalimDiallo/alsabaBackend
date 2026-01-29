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

        profile_data = self._get_profile_data(user)
        
        logger.info("profile_viewed", user_id=str(user.id))

        return Response({
            "success": True,
            "profile": profile_data,
            "metadata": {
                "retrieved_at": timezone.now().isoformat(),
                "requires_kyc": user.kyc_status != 'verified'
            }
        }, status=status.HTTP_200_OK)

    def patch(self, request):
        """
        Mise à jour partielle du profil
        """
        user = request.user
        from ..Serializers.profile import ProfileUpdateSerializer
        
        serializer = ProfileUpdateSerializer(
            user, 
            data=request.data, 
            partial=True,
            context={'request': request}
        )
        
        if serializer.is_valid():
            user = serializer.save()
            user.profile_updated_at = timezone.now()
            user.save(update_fields=['profile_updated_at'])
            
            # Retourner le profil complet mis à jour via le helper
            profile_data = self._get_profile_data(user)
            
            logger.info("profile_updated", user_id=str(user.id))
            
            return Response({
                "success": True,
                "message": "Profil mis à jour avec succès",
                "profile": profile_data
            }, status=status.HTTP_200_OK)
            
        return Response({
            "success": False,
            "error": "Données invalides",
            "details": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

    def _get_profile_data(self, user):
        """
        Prépare les données enrichies du profil
        """
        from ..Serializers.profile import ProfileSerializer
        serializer = ProfileSerializer(user)
        profile_data = serializer.data
        
        # Enrichissement
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
        return profile_data



    def _calculate_profile_completion(self, user):
        """
        Calcule le pourcentage de complétion du profil.
        """
        # Liste des champs avec leur poids
        fields = [
            (user.phone_verified, 2),  # Téléphone vérifié + numéro
            (user.first_name, 1),
            (user.last_name, 1),
            (user.email, 1),
            (user.kyc_status == 'verified', 2),  # KYC + date de naissance
            (user.kyc_document_number, 0.5),  # Bonus
            (user.kyc_address, 0.5),  # Bonus
            (user.city, 0.5),  # Bonus
            (user.postal_code, 0.5),  # Bonus
            (user.state, 0.5),  # Bonus
        ]
        
        total_possible = sum(weight for _, weight in fields)
        completed = sum(weight for condition, weight in fields if condition)
        
        return min(100, int((completed / total_possible) * 100)) if total_possible > 0 else 0

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

        if not user.city or not user.postal_code or not user.state:
            next_steps.append({
                "action": "complete_address",
                "priority": "medium",
                "message": "Complétez vos informations d'adresse pour faciliter vos paiements"
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