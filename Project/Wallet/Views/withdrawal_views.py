"""
Vues pour les retraits
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
    WithdrawalRequestSerializer,
    WithdrawalResponseSerializer,
    PaymentInitiationResponseSerializer,
    ErrorResponseSerializer,
    WalletErrorResponseSerializer,
)
from ..exceptions import (
    WalletError,
    WalletNotFoundError,
    WalletInactiveError,
    InsufficientFundsError,
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


class WithdrawalInitiateView(APIView):
    """
    POST /api/wallet/withdraw/initiate/
    
    Initie un retrait via un provider de paiement
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """
        Initie un retrait
        """
        user = request.user
        
        logger.info(
            "withdrawal_initiate_request",
            user_id=str(user.id),
            kyc_status=user.kyc_status
        )
        
        # Validation des données d'entrée
        serializer = WithdrawalRequestSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(
                "withdrawal_initiate_validation_failed",
                user_id=str(user.id),
                errors=serializer.errors
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Données validées
        amount = serializer.validated_data['amount']
        payment_method = serializer.validated_data['payment_method']
        description = serializer.validated_data.get('description', '')
        bank_account_id = serializer.validated_data.get('bank_account_id')
        
        try:
            # Récupérer le wallet
            wallet = WalletService.get_user_wallet(user)
            if not wallet:
                raise WalletNotFoundError(user_id=str(user.id))
            
            # Vérifier que le wallet est actif
            if not wallet.is_active:
                raise WalletInactiveError(wallet_id=str(wallet.id))
            
            # Vérifier KYC (obligatoire pour les retraits)
            if user.kyc_status != 'verified':
                raise KYCRequiredError(operation="retrait")
            
            # Valider l'opération avant de contacter le provider
            validation = WalletService.validate_wallet_operation(
                wallet=wallet,
                amount=amount,
                operation='withdrawal',
                check_kyc=False  # Déjà vérifié
            )
            
            if not validation['can_proceed']:
                error_data = ErrorResponseSerializer({
                    'success': False,
                    'error': '; '.join(validation['errors']),
                    'code': 'validation_failed',
                    'details': validation,
                }).data
                return Response(error_data, status=status.HTTP_400_BAD_REQUEST)
            
            # Récupérer le provider de paiement
            try:
                provider = PaymentProviderFactory.get_provider(payment_method)
            except PaymentMethodNotSupportedError as e:
                logger.warning(
                    "withdrawal_payment_method_not_supported",
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
                'bank_account_id': bank_account_id,
                'wallet_id': str(wallet.id),
                'wallet_currency': wallet.currency.code,
                'current_balance': float(wallet.balance),
                'estimated_fee': validation.get('fee', 0),
            }
            
            # Initier le retrait avec le provider
            provider_response = provider.initiate_withdrawal(
                amount=amount,
                currency=wallet.currency.code,
                user_data=user_data,
                metadata=metadata
            )
            
            # Vérifier que les frais dans la réponse ne dépassent pas les fonds
            provider_fee = Decimal(str(provider_response.get('fee', 0)))
            total_required = amount + provider_fee
            
            if wallet.available_balance < total_required:
                logger.error(
                    "withdrawal_insufficient_funds_after_provider_fee",
                    user_id=str(user.id),
                    available=float(wallet.available_balance),
                    required=float(total_required)
                )
                
                error_data = ErrorResponseSerializer({
                    'success': False,
                    'error': f"Frais du provider trop élevés. Disponible: {wallet.available_balance}, Requiert: {total_required}",
                    'code': "insufficient_funds_after_fees",
                    'available': float(wallet.available_balance),
                    'required': float(total_required),
                }).data
                
                return Response(error_data, status=status.HTTP_400_BAD_REQUEST)
            
            # Créer une transaction en attente
            # (Dans une version réelle, on créerait une Transaction PENDING)
            transaction_id = uuid.uuid4()
            
            logger.info(
                "withdrawal_initiated_successfully",
                user_id=str(user.id),
                transaction_id=str(transaction_id),
                amount=float(amount),
                payment_method=payment_method,
                provider=provider.name,
                fee=float(provider_fee)
            )
            
            # Préparer la réponse
            response_data = PaymentInitiationResponseSerializer({
                'success': True,
                'message': 'Retrait initié avec succès',
                'transaction_id': transaction_id,
                'provider_response': provider_response,
                'next_steps': provider_response.get('instructions', {})
            }).data
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except KYCRequiredError as e:
            logger.warning(
                "withdrawal_kyc_required",
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
            
        except WalletNotFoundError as e:
            logger.warning(
                "withdrawal_wallet_not_found",
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
            logger.warning(
                "withdrawal_wallet_inactive",
                user_id=str(user.id),
                error_message=e.message
            )
            
            error_data = WalletErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
                'wallet_id': e.details.get('wallet_id'),
            }).data
            
            return Response(error_data, status=status.HTTP_400_BAD_REQUEST)
            
        except InsufficientFundsError as e:
            logger.warning(
                "withdrawal_insufficient_funds",
                user_id=str(user.id),
                amount=float(amount),
                available=float(wallet.available_balance) if 'wallet' in locals() else 0
            )
            
            error_data = WalletErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
                'available_balance': e.details.get('available'),
                'required_amount': e.details.get('required'),
            }).data
            
            return Response(error_data, status=status.HTTP_400_BAD_REQUEST)
            
        except (InvalidAmountError, AmountTooSmallError, AmountTooLargeError) as e:
            logger.warning(
                "withdrawal_invalid_amount",
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
                "withdrawal_payment_method_not_supported",
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
                "withdrawal_payment_error",
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
                "withdrawal_wallet_error",
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
                "withdrawal_initiate_unexpected_error",
                user_id=str(user.id),
                error=str(e),
                exc_info=True
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': "Erreur interne lors de l'initiation du retrait",
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


class WithdrawalConfirmView(APIView):
    """
    POST /api/wallet/withdraw/confirm/
    
    Confirme un retrait après succès du provider
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """
        Confirme un retrait
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
            "withdrawal_confirm_request",
            user_id=str(user.id),
            transaction_id=transaction_id,
            payment_method=payment_method
        )
        
        try:
            # Convertir le montant en Decimal
            amount = Decimal(str(amount))
            
            # Traiter le retrait
            transaction = WalletService.process_withdrawal(
                user=user,
                amount=amount,
                payment_method=payment_method,
                provider_response=provider_response,
                description=f"Retrait confirmé - Transaction: {transaction_id}"
            )
            
            # Sérialiser la réponse
            from ..serializers import TransactionSerializer
            transaction_serializer = TransactionSerializer(transaction)
            
            response_data = WithdrawalResponseSerializer({
                'success': True,
                'message': 'Retrait confirmé avec succès',
                'transaction': transaction_serializer.data,
                'new_balance': float(transaction.wallet.balance),
                'provider_response': provider_response,
            }).data
            
            logger.info(
                "withdrawal_confirmed_successfully",
                user_id=str(user.id),
                transaction_id=str(transaction.id),
                amount=float(amount),
                new_balance=float(transaction.wallet.balance)
            )
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except KYCRequiredError as e:
            logger.warning(
                "withdrawal_confirm_kyc_required",
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
            
        except (WalletNotFoundError, WalletInactiveError) as e:
            logger.warning(
                "withdrawal_confirm_wallet_error",
                user_id=str(user.id),
                error_message=e.message
            )
            
            error_data = WalletErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
                'user_id': str(user.id),
            }).data
            
            return Response(error_data, status=status.HTTP_400_BAD_REQUEST)
            
        except InsufficientFundsError as e:
            logger.warning(
                "withdrawal_confirm_insufficient_funds",
                user_id=str(user.id),
                amount=float(amount)
            )
            
            error_data = WalletErrorResponseSerializer({
                'success': False,
                'error': e.message,
                'code': e.code,
                'available_balance': e.details.get('available'),
                'required_amount': e.details.get('required'),
            }).data
            
            return Response(error_data, status=status.HTTP_400_BAD_REQUEST)
            
        except (InvalidAmountError, AmountTooSmallError, AmountTooLargeError) as e:
            logger.warning(
                "withdrawal_confirm_invalid_amount",
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
                "withdrawal_confirm_wallet_error",
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
                "withdrawal_confirm_unexpected_error",
                user_id=str(user.id),
                error=str(e),
                exc_info=True
            )
            
            error_data = ErrorResponseSerializer({
                'success': False,
                'error': "Erreur interne lors de la confirmation du retrait",
                'code': "internal_error",
            }).data
            
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)