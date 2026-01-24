# wallet/views.py (version corrigée)

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
import structlog

from ..models import Wallet
from ..Serializers.walletSerializers import WalletSerializer
from Accounts.utils import auth_utils

logger = structlog.get_logger(__name__)


class WalletDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        try:
            wallet = Wallet.create_for_user(user)
            serializer = WalletSerializer(wallet)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except ValueError as e:
            logger.error("wallet_creation_failed", user_id=str(user.id), error=str(e))
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


