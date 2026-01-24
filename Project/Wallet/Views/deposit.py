# wallet/views.py (version corrigée)

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
import structlog

from ..models import Wallet
from ..Serializers.walletSerializers import DepositSerializer
from ..Services.CardServices import DepositService
from Accounts.utils import auth_utils

logger = structlog.get_logger(__name__)

class DepositView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        
        if user.kyc_status != 'verified':
            return Response({"error": "KYC requis pour les dépôts."}, status=status.HTTP_403_FORBIDDEN)

        # Correction ici : utilisation de auth_utils.is_rate_limited
        rate_limit_key = f"deposit_{user.id}"
        if auth_utils.is_rate_limited(rate_limit_key, limit=5, window_seconds=3600):
            return Response(
                {"error": "Trop de tentatives de dépôt. Réessayez plus tard."},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        serializer = DepositSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            wallet = user.wallet
        except AttributeError:
            return Response({"error": "Wallet non créé."}, status=status.HTTP_404_NOT_FOUND)

        amount = serializer.validated_data['amount']
        method = serializer.validated_data['method']
        reference = serializer.validated_data.get('reference', '')

        result = DepositService.process_deposit(wallet, amount, method, reference)
        
        if result['success']:
            return Response(result, status=status.HTTP_200_OK)
        else:
            return Response({"error": result['message']}, status=status.HTTP_400_BAD_REQUEST)