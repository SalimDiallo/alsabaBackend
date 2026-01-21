"""
Vues pour les dépôts
"""
import uuid
import logging
from decimal import Decimal
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from ..Services.wallet_service import WalletService
from ..Services.PayementProviders.base import PaymentProviderFactory
from ..serializers import (
    DepositRequestSerializer,
    DepositResponseSerializer,
    PaymentInitiationResponseSerializer,
    ErrorResponseSerializer,
    WalletErrorResponseSerializer,
)
from ..exceptions import (
    WalletError,
    WalletNotFoundError,
    InvalidAmountError,
    AmountTooSmallError,
    AmountTooLargeError,
    PaymentError,
    PaymentMethodNotSupportedError,
    PaymentProviderError,
    KYCRequiredError,
)
import structlog
logger = structlog.get_logger(__name__)


class DepositInitiateView(APIView):
    """
    POST /api/wallet/deposit/initiate/
    
    Initie un dépôt via un provider de paiement
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """
        Initie un dépôt
        """
        user = request.user
        
        logger.info(
            "deposit_initiate_request",
            user_id=str(user.id),
            kyc_status=user.kyc_status
        )
        
        # Validation des données d'entrée
        serializer = DepositRequestSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(
                "deposit_initiate_validation_failed",
                user_id=str(user.id),
                errors=serializer.errors
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Données validées
        amount = serializer.validated_data['amount']
        payment_method = serializer.validated_data['payment_method']
        description = serializer.validated_data.get('description', '')
        card_token = serializer.validated_data.get('card_token')
        
        try:
            # Récupérer le wallet
            wallet = WalletService.get_user_wallet(user)
            if not wallet:
                wallet = WalletService.create_wallet_for_user(user)
                logger.info(
                    "wallet_created_during_deposit",
                    user_id=str(user.id),
                    wallet_id=str(wallet.id)
                )
            
            # Vérifier KYC pour les gros montants
            if amount > Decimal('1000') and user.kyc_status != 'verified':
                raise KYCRequiredError(
                    operation=f"dépôt de {amount} {wallet.currency.code}"
                )
            
            # Récupérer le provider de paiement
            try:
                provider = PaymentProviderFactory.get_provider(payment_method)
            except PaymentMethodNotSupportedError as e:
                logger.warning(
                    "payment_method_not_supported",
                    user_id=str(user.id),
                    payment_method=payment_method,
                    currency=wallet.currency.code
                )
                raise e
            
            # Vérifier que la devise est supportée par le provider
            if wallet.currency.code not in provider.supported_currencies:
                raise PaymentMethodNotSupportedError(
                    payment_method=payment_method,
                    currency=wallet.currency.code
                )
            
            # Préparer les données utilisateur
            user_data = {
                'user_id': str(user.id),
                'phone': user.full_phone_number,
                'email': user.email or '',
                'first_name': user.first_name or '',
                'last_name': user.last_name or '',
                'full_name': f"{user.first_name or ''} {user.last_name or ''}".strip(),
            }
            
            # Préparer les métadonnées
            metadata = {
                'timestamp': timezone.now().isoformat(),
                'user_ip': self._get_client_ip(request),
                'description': description,
                'card_token': card_token,
                'wallet_id': str(wallet.id),
                'wallet_currency': wallet.currency.code,
            }
            
            # Initier le dépôt avec le provider
            provider_response = provider.initiate_deposit(
                amount=amount,
                currency=wallet.currency.code,
                user_data=user_data,
                metadata=metadata
            )
            
            # Créer une transaction en attente
            # (Dans une version réelle, on créerait une Transaction PENDING)
            # Pour la simulation, on retourne directement la réponse du provider
            
            transaction_id = uuid.uuid4()
            
            logger.info(
                "deposit_initiated_successfully",
                user_id=str(user.id),
                transaction_id=str(transaction_id),
                amount=float(amount),
                payment_method=payment_method,
                provider=provider.name
            )
            
            # Préparer la réponse
            response_data = PaymentInitiationResponseSerializer({
                'success': True,
                'message': 'Dépôt initié avec succès',
                'transaction_id': transaction_id,
                'provider_response': provider_response,
                'next_steps': provider_response.get('instructions', {})
            }).data
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except KYCRequiredError as e:
            logger.warning(
                "deposit_kyc_required",
                user_id=str(user.id),
                amount=float(amount)
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
                'next_step': 'complete_kyc',
            }).data
            
            return Response(error_data, status=status.HTTP_403_FORBIDDEN)
            
        except (InvalidAmountError, AmountTooSmallError, AmountTooLargeError) as e:
            logger.warning(
                "deposit_invalid_amount",
                user_id=str(user.id),
                amount=float(amount),
                error_message=e.message
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
            }).data
            
            return Response(error_data, status=status.HTTP_400_BAD_REQUEST)
            
        except PaymentMethodNotSupportedError as e:
            logger.warning(
                "deposit_payment_method_not_supported",
                user_id=str(user.id),
                payment_method=payment_method,
                error_message=e.message
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
            }).data
            
            return Response(error_data, status=status.HTTP_400_BAD_REQUEST)
            
        except (PaymentError, PaymentProviderError) as e:
            logger.error(
                "deposit_payment_error",
                user_id=str(user.id),
                payment_method=payment_method,
                error=str(e),
                error_code=e.code
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
            }).data
            
            return Response(error_data, status=status.HTTP_400_BAD_REQUEST)
            
        except WalletError as e:
            logger.error(
                "deposit_wallet_error",
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
                "deposit_initiate_unexpected_error",
                user_id=str(user.id),
                error=str(e),
                exc_info=True
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': "Erreur interne lors de l'initiation du dépôt",
                'code': "internal_error",
            }).data
            
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_client_ip(self, request):
        """Récupère l'IP du client"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class DepositConfirmView(APIView):
    """
    POST /api/wallet/deposit/confirm/
    
    Confirme un dépôt après succès du provider
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """
        Confirme un dépôt
        """
        user = request.user
        
        # Récupérer les données de la requête
        transaction_id = request.data.get('transaction_id')
        provider_response = request.data.get('provider_response', {})
        amount = request.data.get('amount')
        payment_method = request.data.get('payment_method')
        
        if not all([transaction_id, provider_response, amount, payment_method]):
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': "Données incomplètes",
                'code': "missing_data",
            }).data
            
            return Response(error_data, status=status.HTTP_400_BAD_REQUEST)
        
        logger.info(
            "deposit_confirm_request",
            user_id=str(user.id),
            transaction_id=transaction_id,
            payment_method=payment_method
        )
        
        try:
            # Convertir le montant en Decimal
            amount = Decimal(str(amount))
            
            # Traiter le dépôt
            transaction = WalletService.process_deposit(
                user=user,
                amount=amount,
                payment_method=payment_method,
                provider_response=provider_response,
                description=f"Dépôt confirmé - Transaction: {transaction_id}"
            )
            
            # Sérialiser la réponse
            from ..serializers import TransactionSerializer
            transaction_serializer = TransactionSerializer(transaction)
            
            response_data = DepositResponseSerializer({
                'success': True,
                'message': 'Dépôt confirmé avec succès',
                'transaction': transaction_serializer.data,
                'new_balance': float(transaction.wallet.balance),
                'provider_response': provider_response,
            }).data
            
            logger.info(
                "deposit_confirmed_successfully",
                user_id=str(user.id),
                transaction_id=str(transaction.id),
                amount=float(amount)
            )
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except KYCRequiredError as e:
            logger.warning(
                "deposit_confirm_kyc_required",
                user_id=str(user.id),
                amount=float(amount)
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
                'next_step': 'complete_kyc',
            }).data
            
            return Response(error_data, status=status.HTTP_403_FORBIDDEN)
            
        except (InvalidAmountError, AmountTooSmallError, AmountTooLargeError) as e:
            logger.warning(
                "deposit_confirm_invalid_amount",
                user_id=str(user.id),
                amount=float(amount),
                error_message=e.message
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
            }).data
            
            return Response(error_data, status=status.HTTP_400_BAD_REQUEST)
            
        except WalletError as e:
            logger.error(
                "deposit_confirm_wallet_error",
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
                "deposit_confirm_unexpected_error",
                user_id=str(user.id),
                error=str(e),
                exc_info=True
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': "Erreur interne lors de la confirmation du dépôt",
                'code': "internal_error",
            }).data
            
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)