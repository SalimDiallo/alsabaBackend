# apps/auth/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from ..Serializers.profile import ProfileSerializer

class ProfileView(APIView):
    """
    GET /api/profile/
    
    Retourne le profil complet de l'utilisateur connecté
    - Statut téléphone
    - Statut KYC
    - Données extraites par Didit
    - Dates importantes
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        serializer = ProfileSerializer(user)
        
        # Ajout d'informations contextuelles utiles
        profile_data = serializer.data
        
        profile_data['next_steps'] = []
        
        if not user.phone_verified:
            profile_data['next_steps'].append("verify_phone")
        
        if user.kyc_status == 'unverified':
            profile_data['next_steps'].append("complete_kyc")
        elif user.kyc_status == 'rejected':
            if user.kyc_retry_count < 3:
                profile_data['next_steps'].append("retry_kyc")
            else:
                profile_data['next_steps'].append("kyc_max_retries")
        
        return Response({
            "success": True,
            "profile": profile_data
        }, status=status.HTTP_200_OK)