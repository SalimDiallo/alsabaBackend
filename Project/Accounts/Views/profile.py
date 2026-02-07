# apps/auth/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from ..Serializers.profile import ProfileSerializer, ProfileUpdateSerializer
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from django.utils import timezone
import structlog    
logger = structlog.get_logger(__name__)
class ProfileView(APIView):
    """
    GET /api/profile/
    
    Retourne le profil complet de l'utilisateur connecté
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Récupérer le profil utilisateur",
        description="Retourne les informations détaillées du profil, y compris le statut de vérification et le pourcentage de complétion.",
        tags=['Profil & KYC'],
        responses={
            200: inline_serializer(
                name='ProfileResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'profile': ProfileSerializer(),
                    'metadata': inline_serializer(
                        name='ProfileMetadata',
                        fields={
                            'retrieved_at': serializers.DateTimeField(),
                            'requires_kyc': serializers.BooleanField()
                        }
                    )
                }
            )
        }
    )
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

        serializer = ProfileSerializer(user)
        
        logger.info("profile_viewed", user_id=str(user.id))

        return Response({
            "success": True,
            "profile": serializer.data,
            "metadata": {
                "retrieved_at": timezone.now().isoformat(),
                "requires_kyc": user.kyc_status != 'verified'
            }
        }, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Mettre à jour le profil",
        description="Permet de mettre à jour partiellement les informations du profil (email, nom, etc.).",
        request=ProfileUpdateSerializer,
        tags=['Profil & KYC'],
        responses={
            200: inline_serializer(
                name='ProfileUpdateResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'message': serializers.CharField(),
                    'profile': ProfileSerializer()
                }
            )
        }
    )
    def patch(self, request):
        """
        Mise à jour partielle du profil
        """
        user = request.user
        
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
            
            logger.info("profile_updated", user_id=str(user.id))
            
            return Response({
                "success": True,
                "message": "Profil mis à jour avec succès",
                "profile": ProfileSerializer(user).data
            }, status=status.HTTP_200_OK)
            
        return Response({
            "success": False,
            "error": "Données invalides",
            "details": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)