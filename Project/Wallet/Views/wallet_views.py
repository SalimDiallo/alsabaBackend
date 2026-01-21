"""
Vues pour la gestion des wallets
"""
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from ..Services.wallet_service import WalletService
from ..serializers import (
    WalletSerializer,
    WalletSummarySerializer,
    ErrorResponseSerializer,
    WalletErrorResponseSerializer,
)
from ..exceptions import (
    WalletError,
    WalletNotFoundError,
    WalletInactiveError,
)

import structlog
logger = structlog.get_logger(__name__)


class WalletView(APIView):
    """
    GET /api/wallet/
    
    Récupère le wallet de l'utilisateur connecté
    Crée le wallet s'il n'existe pas
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Récupère ou crée le wallet de l'utilisateur
        """
        user = request.user
        
        logger.info(
            "wallet_view_request",
            user_id=str(user.id),
            phone_verified=user.phone_verified
        )
        
        # Vérifier que le téléphone est vérifié
        if not user.phone_verified:
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': "Votre numéro de téléphone doit être vérifié",
                'code': "phone_not_verified",
                'next_step': "verify_phone"
            }).data
            
            return Response(error_data, status=status.HTTP_403_FORBIDDEN)
        
        try:
            # Récupérer le wallet existant ou en créer un nouveau
            wallet = WalletService.get_user_wallet(user)
            
            if not wallet:
                # Créer le wallet pour l'utilisateur
                wallet = WalletService.create_wallet_for_user(user)
                logger.info(
                    "wallet_created_on_request",
                    user_id=str(user.id),
                    wallet_id=str(wallet.id)
                )
            
            # Sérialiser le wallet
            serializer = WalletSerializer(wallet)
            
            response_data = {
                'success': True,
                'wallet': serializer.data,
                'metadata': {
                    'retrieved_at': timezone.now().isoformat(),
                    'requires_kyc': user.kyc_status != 'verified',
                    'kyc_status': user.kyc_status,
                }
            }
            
            logger.debug(
                "wallet_view_success",
                user_id=str(user.id),
                wallet_id=str(wallet.id)
            )
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except WalletError as e:
            logger.warning(
                "wallet_view_wallet_error",
                user_id=str(user.id),
                error_code=e.code,
                error_message=e.message
            )
            
            error_data = WalletErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
                'user_id': str(user.id),
                'details': e.details,
            }).data
            
            return Response(error_data, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            logger.error(
                "wallet_view_unexpected_error",
                user_id=str(user.id),
                error=str(e),
                exc_info=True
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': "Erreur interne lors de la récupération du wallet",
                'code': "internal_error",
            }).data
            
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WalletSummaryView(APIView):
    """
    GET /api/wallet/summary/
    
    Récupère un résumé détaillé du wallet
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Récupère le résumé du wallet
        """
        user = request.user
        
        logger.debug(
            "wallet_summary_request",
            user_id=str(user.id)
        )
        
        try:
            # Récupérer le wallet
            wallet = WalletService.get_user_wallet(user)
            
            if not wallet:
                raise WalletNotFoundError(user_id=str(user.id))
            
            # Récupérer le résumé
            summary = WalletService.get_wallet_summary(wallet)
            
            # Sérialiser la réponse
            serializer = WalletSummarySerializer(summary)
            
            response_data = {
                'success': True,
                'summary': serializer.data,
            }
            
            logger.debug(
                "wallet_summary_success",
                user_id=str(user.id),
                wallet_id=str(wallet.id)
            )
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except WalletNotFoundError as e:
            logger.warning(
                "wallet_summary_not_found",
                user_id=str(user.id),
                error_message=e.message
            )
            
            error_data = WalletErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
                'user_id': str(user.id),
            }).data
            
            return Response(error_data, status=status.HTTP_404_NOT_FOUND)
            
        except WalletInactiveError as e:
            error_data = WalletErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
                'wallet_id': e.details.get('wallet_id'),
            }).data
            
            return Response(error_data, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            logger.error(
                "wallet_summary_unexpected_error",
                user_id=str(user.id),
                error=str(e),
                exc_info=True
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': "Erreur interne lors de la récupération du résumé",
                'code': "internal_error",
            }).data
            
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)