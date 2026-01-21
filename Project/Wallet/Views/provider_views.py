"""
Vues pour les providers de paiement
"""
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from ..Services.wallet_service import WalletService
from ..Services.PayementProviders.base import PaymentProviderFactory
from ..serializers import (
    PaymentProviderSerializer,
    ErrorResponseSerializer,
    WalletErrorResponseSerializer,
)
from ..exceptions import WalletError, WalletNotFoundError

import structlog
logger = structlog.get_logger(__name__)

class PaymentProvidersView(APIView):
    """
    GET /api/wallet/payment-providers/
    
    Liste les providers de paiement disponibles pour l'utilisateur
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Récupère la liste des providers disponibles
        Filtrée par la devise du wallet de l'utilisateur
        """
        user = request.user
        
        logger.debug(
            "payment_providers_request",
            user_id=str(user.id)
        )
        
        try:
            # Récupérer le wallet
            wallet = WalletService.get_user_wallet(user)
            if not wallet:
                wallet = WalletService.create_wallet_for_user(user)
                logger.info(
                    "wallet_created_for_providers",
                    user_id=str(user.id),
                    wallet_id=str(wallet.id)
                )
            
            # Récupérer tous les providers
            all_providers_info = PaymentProviderFactory.get_all_providers_info()
            
            # Filtrer par devise supportée
            available_providers = []
            currency = wallet.currency.code
            
            for provider_name, provider_info in all_providers_info.items():
                if currency in provider_info.get('supported_currencies', []):
                    available_providers.append(provider_info)
            
            # Sérialiser les providers
            serializer = PaymentProviderSerializer(available_providers, many=True)
            
            response_data = {
                'success': True,
                'currency': currency,
                'providers': serializer.data,
                'metadata': {
                    'total_providers': len(available_providers),
                    'currency_name': wallet.currency.name,
                    'currency_symbol': wallet.currency.symbol,
                }
            }
            
            logger.debug(
                "payment_providers_success",
                user_id=str(user.id),
                currency=currency,
                providers_count=len(available_providers)
            )
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except WalletError as e:
            logger.error(
                "payment_providers_wallet_error",
                user_id=str(user.id),
                error=str(e)
            )
            
            error_data = WalletErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
                'user_id': str(user.id),
            }).data
            
            return Response(error_data, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            logger.error(
                "payment_providers_unexpected_error",
                user_id=str(user.id),
                error=str(e),
                exc_info=True
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': "Erreur interne lors de la récupération des providers",
                'code': "internal_error",
            }).data
            
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)