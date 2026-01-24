from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from Accounts.utils import auth_utils
from ..Services.CardServices import WithdrawalService
from ..Serializers.walletSerializers import WithdrawalSerializer
import structlog
class WithdrawalView(APIView):
    """
    POST /api/wallet/withdraw/
    - Demande un retrait (placeholder pour l'instant)
    - Requiert KYC verified
    - Rate limiting: 3 retraits/heure
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        
        if user.kyc_status != 'verified':
            return Response({"error": "KYC requis pour les retraits."}, status=status.HTTP_403_FORBIDDEN)

        # Rate limiting sur les retraits
        rate_limit_key = f"withdraw_{user.id}"
        if auth_utils.is_rate_limited(rate_limit_key, limit=3, window_seconds=3600):
            return Response(
                {"error": "Trop de tentatives de retrait. Réessayez plus tard."},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        serializer = WithdrawalSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            wallet = user.wallet
        except AttributeError:
            return Response({"error": "Wallet non créé."}, status=status.HTTP_404_NOT_FOUND)

        amount = serializer.validated_data['amount']
        method = serializer.validated_data['method']
        reference = serializer.validated_data.get('reference', '')

        result = WithdrawalService.process_withdrawal(wallet, amount, method, reference)
        
        if result['success']:
            return Response(result, status=status.HTTP_200_OK)
        else:
            return Response({"error": result['message']}, status=status.HTTP_400_BAD_REQUEST)