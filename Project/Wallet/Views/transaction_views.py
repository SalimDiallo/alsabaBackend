"""
Vues pour l'historique des transactions
"""
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from datetime import datetime, timedelta

from ..Services.wallet_service import WalletService
from ..serializers import (
    TransactionHistoryResponseSerializer,
    ErrorResponseSerializer,
    WalletErrorResponseSerializer,
)
from ..exceptions import (
    WalletError,
    WalletNotFoundError,
)

import structlog
logger = structlog.get_logger(__name__)

class TransactionHistoryView(APIView):
    """
    GET /api/wallet/transactions/
    
    Récupère l'historique des transactions du wallet
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Récupère l'historique des transactions avec pagination
        """
        user = request.user
        
        # Récupérer les paramètres de pagination
        limit = int(request.GET.get('limit', 50))
        offset = int(request.GET.get('offset', 0))
        
        # Récupérer les filtres optionnels
        transaction_type = request.GET.get('type')
        days = request.GET.get('days')
        
        # Calculer les dates si days est fourni
        start_date = None
        end_date = timezone.now()
        
        if days:
            try:
                days = int(days)
                start_date = end_date - timedelta(days=days)
            except ValueError:
                pass
        
        logger.debug(
            "transaction_history_request",
            user_id=str(user.id),
            limit=limit,
            offset=offset,
            transaction_type=transaction_type,
            days=days
        )
        
        try:
            # Récupérer le wallet
            wallet = WalletService.get_user_wallet(user)
            
            if not wallet:
                raise WalletNotFoundError(user_id=str(user.id))
            
            # Récupérer l'historique
            history = WalletService.get_transaction_history(
                wallet=wallet,
                limit=limit,
                offset=offset,
                transaction_type=transaction_type,
                start_date=start_date,
                end_date=end_date
            )
            
            # Sérialiser la réponse
            from ..serializers import TransactionSerializer
            transaction_serializer = TransactionSerializer(history['transactions'], many=True)
            
            response_data = TransactionHistoryResponseSerializer({
                'transactions': transaction_serializer.data,
                'pagination': history['pagination'],
                'summary': history.get('summary', {})
            }).data
            
            logger.debug(
                "transaction_history_success",
                user_id=str(user.id),
                total_transactions=history['pagination']['total'],
                returned_transactions=len(history['transactions'])
            )
            
            return Response({
                'success': True,
                **response_data
            }, status=status.HTTP_200_OK)
            
        except WalletNotFoundError as e:
            logger.warning(
                "transaction_history_wallet_not_found",
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
            
        except Exception as e:
            logger.error(
                "transaction_history_unexpected_error",
                user_id=str(user.id),
                error=str(e),
                exc_info=True
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': "Erreur interne lors de la récupération de l'historique",
                'code': "internal_error",
            }).data
            
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TransactionDetailView(APIView):
    """
    GET /api/wallet/transactions/<transaction_id>/
    
    Récupère les détails d'une transaction spécifique
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, transaction_id):
        """
        Récupère les détails d'une transaction
        """
        user = request.user
        
        logger.debug(
            "transaction_detail_request",
            user_id=str(user.id),
            transaction_id=transaction_id
        )
        
        try:
            # Récupérer le wallet de l'utilisateur
            wallet = WalletService.get_user_wallet(user)
            if not wallet:
                raise WalletNotFoundError(user_id=str(user.id))
            
            # Récupérer la transaction
            from ..models import Transaction
            try:
                transaction = Transaction.objects.get(
                    id=transaction_id,
                    wallet=wallet
                )
            except Transaction.DoesNotExist:
                from ..exceptions import TransactionNotFoundError
                raise TransactionNotFoundError(transaction_id=transaction_id)
            
            # Sérialiser la transaction
            from ..serializers import TransactionSerializer
            serializer = TransactionSerializer(transaction)
            
            logger.debug(
                "transaction_detail_success",
                user_id=str(user.id),
                transaction_id=transaction_id
            )
            
            return Response({
                'success': True,
                'transaction': serializer.data
            }, status=status.HTTP_200_OK)
            
        except WalletNotFoundError as e:
            error_data = WalletErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
                'user_id': str(user.id),
            }).data
            
            return Response(error_data, status=status.HTTP_404_NOT_FOUND)
            
        except Exception as e:
            logger.error(
                "transaction_detail_unexpected_error",
                user_id=str(user.id),
                transaction_id=transaction_id,
                error=str(e),
                exc_info=True
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': "Erreur interne lors de la récupération des détails de la transaction",
                'code': "internal_error",
            }).data
            
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)