from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Q
import structlog

from ..models import Wallet, Transaction
from Accounts.utils import auth_utils
from ..Services.wallet_service import wallet_service, WalletService
from ..Serializers.wallet_serializers import (
    WalletSerializer,
    TransactionSerializer,
    DepositSerializer,
    WithdrawalSerializer,
    TransactionListSerializer,
    TransactionConfirmSerializer,
    TransactionCancelSerializer,
    TransactionStatusUpdateSerializer
)

logger = structlog.get_logger(__name__)


class WalletView(APIView):
    """
    GET /api/wallet/
    Récupère les informations du portefeuille de l'utilisateur
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = wallet_service.get_or_create_wallet(request.user)

        serializer = WalletSerializer(wallet)
        data = serializer.data

        # Ajout d'informations supplémentaires
        data['transactions_count'] = wallet.transactions.count()
        data['recent_transactions'] = TransactionSerializer(
            wallet.transactions.order_by('-created_at')[:5],
            many=True
        ).data
        data['currency_info'] = {
            'code': wallet.currency,
            'symbol': WalletService._get_currency_symbol(wallet.currency),
            'name': WalletService._get_currency_name(wallet.currency)
        }

        logger.info("wallet_viewed", user_id=str(request.user.id), balance=wallet.balance)

        return Response({
            "success": True,
            "wallet": data
        }, status=status.HTTP_200_OK)


class DepositView(APIView):
    """
    POST /api/wallet/deposit/
    Initie un dépôt sur le portefeuille
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DepositSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(
                "deposit_validation_failed",
                user_id=str(request.user.id),
                errors=serializer.errors
            )
            return Response({
                "success": False,
                "error": "Données invalides",
                "details": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        # Extraction sécurisée des métadonnées (IP réelle, Agent, etc.)
        request_meta = auth_utils.extract_request_metadata(request)

        # Extraction des détails de carte si méthode card et pas de payment_method_id
        card_details = None
        validated_data = serializer.validated_data
        payment_method_id = validated_data.get('payment_method_id')
        
        if validated_data['payment_method'] == 'card':
            # Si payment_method_id fourni, on a juste besoin du CVV
            if payment_method_id:
                if not validated_data.get('card_cvv'):
                    return Response({
                        "success": False,
                        "error": "CVV requis même avec une méthode sauvegardée",
                        "code": "cvv_required"
                    }, status=status.HTTP_400_BAD_REQUEST)
                card_details = {
                    'cvv': validated_data['card_cvv']
                }
            else:
                # Détails complets requis
                card_details = {
                    'number': validated_data['card_number'],
                    'exp_month': validated_data['card_expiry_month'],
                    'exp_year': validated_data['card_expiry_year'],
                    'cvv': validated_data['card_cvv']
                }

        result = wallet_service.initiate_deposit(
            user=request.user,
            amount=validated_data['amount'],
            payment_method=validated_data['payment_method'],
            card_details=card_details,
            request_meta=request_meta,
            payment_method_id=payment_method_id,
            save_payment_method=validated_data.get('save_payment_method', False),
            payment_method_label=validated_data.get('payment_method_label')
        )

        if not result["success"]:
            return Response({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code"),
                "available_balance": result.get("available_balance")
            }, status=result.get("status_code", status.HTTP_400_BAD_REQUEST))

        # Sérialisation de la transaction
        transaction_data = TransactionSerializer(result["transaction"]).data

        logger.info(
            "deposit_initiated",
            user_id=str(request.user.id),
            transaction_id=str(result["transaction"].id),
            amount=result["amount"],
            payment_method=serializer.validated_data['payment_method']
        )

        return Response({
            "success": True,
            "message": "Dépôt initié avec succès",
            "transaction": transaction_data,
            "payment_link": result["payment_link"],
            "reference": result["reference"],
            "amount": result["amount"],
            "fee": result["fee"],
            "total": result["total"],
            "currency": result.get("currency", "EUR"),
            "currency_info": {
                "code": result.get("currency", "EUR"),
                "symbol": WalletService._get_currency_symbol(result.get("currency", "EUR")),
                "name": WalletService._get_currency_name(result.get("currency", "EUR"))
            },
            "expires_in": 1800  # 30 minutes
        }, status=status.HTTP_201_CREATED)


class WithdrawalView(APIView):
    """
    POST /api/wallet/withdraw/
    Initie un retrait du portefeuille
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = WithdrawalSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(
                "withdrawal_validation_failed",
                user_id=str(request.user.id),
                errors=serializer.errors
            )
            return Response({
                "success": False,
                "error": "Données invalides",
                "details": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        # Préparation des détails du compte selon la méthode
        validated_data = serializer.validated_data
        payment_method = validated_data['payment_method']
        payment_method_id = validated_data.get('payment_method_id')
        
        # Si payment_method_id fourni, account_details sera construit dans wallet_service
        account_details = None
        if not payment_method_id:
            if payment_method == 'card':
                # Retrait vers compte bancaire
                account_details = {
                    'account_number': validated_data['account_number'],
                    'bank_code': validated_data['bank_code'],
                    'account_name': validated_data.get('account_name') or f"{request.user.first_name} {request.user.last_name}".strip() or request.user.full_phone_number,
                    'bank_name': validated_data.get('bank_name'),
                    'bank_country': validated_data.get('bank_country'),
                    'type': 'bank_account'  # Type par défaut
                }
            elif payment_method == 'orange_money':
                account_details = {
                    'phone_number': validated_data['orange_money_number'],
                    'beneficiary_name': f"{request.user.first_name} {request.user.last_name}".strip() or request.user.full_phone_number
                }

        # Extraction sécurisée des métadonnées (IP réelle, Agent, etc.)
        request_meta = auth_utils.extract_request_metadata(request)

        result = wallet_service.initiate_withdrawal(
            user=request.user,
            amount=validated_data['amount'],
            payment_method=payment_method,
            account_details=account_details,
            request_meta=request_meta,
            payment_method_id=payment_method_id,
            save_payment_method=validated_data.get('save_payment_method', False),
            payment_method_label=validated_data.get('payment_method_label')
        )

        if not result["success"]:
            return Response({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code"),
                "available_balance": result.get("available_balance"),
                "required_amount": result.get("required_amount")
            }, status=status.HTTP_400_BAD_REQUEST)

        # Sérialisation de la transaction
        transaction_data = TransactionSerializer(result["transaction"]).data

        logger.info(
            "withdrawal_initiated",
            user_id=str(request.user.id),
            transaction_id=str(result["transaction"].id),
            amount=validated_data['amount'],
            payment_method=payment_method
        )

        return Response({
            "success": True,
            "message": "Retrait initié avec succès",
            "transaction": transaction_data,
            "reference": result["reference"],
            "amount": result["amount"],
            "fee": result["fee"],
            "total_deducted": result["total_deducted"],
            "currency": result.get("currency", request.user.wallet.currency),
            "currency_info": {
                "code": result.get("currency", request.user.wallet.currency),
                "symbol": WalletService._get_currency_symbol(result.get("currency", request.user.wallet.currency)),
                "name": WalletService._get_currency_name(result.get("currency", request.user.wallet.currency))
            }
        }, status=status.HTTP_201_CREATED)


class TransactionListView(APIView):
    """
    GET /api/wallet/transactions/
    Liste les transactions de l'utilisateur avec filtrage
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Validation des paramètres de filtrage
        filter_serializer = TransactionListSerializer(data=request.query_params)
        if not filter_serializer.is_valid():
            return Response({
                "success": False,
                "error": "Paramètres de filtrage invalides",
                "details": filter_serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        filters = filter_serializer.validated_data

        # Récupération du wallet
        wallet = wallet_service.get_or_create_wallet(request.user)

        # Construction de la requête
        queryset = wallet.transactions.all()

        # Application des filtres
        if filters.get('transaction_type'):
            queryset = queryset.filter(transaction_type=filters['transaction_type'])

        if filters.get('status'):
            queryset = queryset.filter(status=filters['status'])

        if filters.get('payment_method'):
            queryset = queryset.filter(payment_method=filters['payment_method'])

        if filters.get('date_from'):
            queryset = queryset.filter(created_at__date__gte=filters['date_from'])

        if filters.get('date_to'):
            queryset = queryset.filter(created_at__date__lte=filters['date_to'])

        # Pagination
        limit = filters.get('limit', 20)
        offset = filters.get('offset', 0)
        total_count = queryset.count()

        transactions = queryset.order_by('-created_at')[offset:offset + limit]

        # Sérialisation
        serializer = TransactionSerializer(transactions, many=True)

        return Response({
            "success": True,
            "transactions": serializer.data,
            "pagination": {
                "total_count": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total_count
            },
            "filters_applied": filters
        }, status=status.HTTP_200_OK)


class TransactionDetailView(APIView):
    """
    GET /api/wallet/transactions/{id}/
    Détail d'une transaction spécifique
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, transaction_id):
        try:
            # Récupération du wallet de l'utilisateur
            wallet = wallet_service.get_or_create_wallet(request.user)

            # Récupération de la transaction (sécurisée par wallet)
            transaction = wallet.transactions.get(id=transaction_id)

            serializer = TransactionSerializer(transaction)

            return Response({
                "success": True,
                "transaction": serializer.data
            }, status=status.HTTP_200_OK)

        except Transaction.DoesNotExist:
            return Response({
                "success": False,
                "error": "Transaction non trouvée",
                "code": "transaction_not_found"
            }, status=status.HTTP_404_NOT_FOUND)


class FlutterwaveWebhookView(APIView):
    """
    POST /api/wallet/webhook/
    Webhook pour recevoir les notifications Flutterwave
    """
    permission_classes = []  # Pas d'authentification pour les webhooks

    def post(self, request):
        """
        Traite les webhooks Flutterwave avec vérification de signature
        """
        try:
            # Récupérer la signature depuis les headers
            signature = request.META.get('HTTP_X_FLUTTERWAVE_SIGNATURE') or \
                       request.META.get('HTTP_SIGNATURE') or \
                       request.META.get('HTTP_X_VERIFY_HASH')
            
            # Récupérer le corps brut pour la vérification
            raw_body = request.body
            
            # Vérifier la signature si configurée
            from Wallet.Services.flutterwave.base import FlutterwaveBaseService
            base_service = FlutterwaveBaseService()
            
            if base_service.webhook_secret and signature:
                if not base_service.verify_webhook_signature(raw_body, signature):
                    logger.warning(
                        "webhook_signature_invalid",
                        signature_provided=signature[:20] + "..." if signature else None
                    )
                    return Response(
                        {"status": "error", "message": "Invalid signature"},
                        status=status.HTTP_401_UNAUTHORIZED
                    )
            elif base_service.webhook_secret and not signature:
                logger.warning("webhook_signature_missing")
                return Response(
                    {"status": "error", "message": "Signature required"},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            webhook_data = request.data

            logger.info(
                "webhook_received",
                event=webhook_data.get("event"),
                data_id=webhook_data.get("data", {}).get("id"),
                signature_valid=True
            )

            result = wallet_service.process_webhook(webhook_data)

            if result["success"]:
                return Response({"status": "success"}, status=status.HTTP_200_OK)
            else:
                return Response(
                    {"status": "error", "message": result.get("error")},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            logger.error("webhook_processing_error", error=str(e))
            return Response(
                {"status": "error", "message": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ConfirmDepositView(APIView):
    """
    POST /api/wallet/deposit/{transaction_id}/confirm/
    Confirme un dépôt (généralement appelé par webhook ou admin)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, transaction_id):
        serializer = TransactionConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "success": False,
                "error": "Données invalides",
                "details": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        result = wallet_service.confirm_deposit(
            user=request.user,
            transaction_id=transaction_id,
            confirmation_data=serializer.validated_data
        )

        if not result["success"]:
            return Response({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code")
            }, status=result.get("status_code", status.HTTP_400_BAD_REQUEST))

        logger.info(
            "deposit_confirmed",
            user_id=str(request.user.id),
            transaction_id=transaction_id,
            amount=result.get("amount")
        )

        return Response({
            "success": True,
            "message": "Dépôt confirmé avec succès",
            "transaction": TransactionSerializer(result["transaction"]).data,
            "wallet_balance": result.get("wallet_balance"),
            "amount_credited": result.get("amount_credited")
        }, status=status.HTTP_200_OK)


class CancelDepositView(APIView):
    """
    POST /api/wallet/deposit/{transaction_id}/cancel/
    Annule un dépôt en attente
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, transaction_id):
        serializer = TransactionCancelSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "success": False,
                "error": "Données invalides",
                "details": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        result = wallet_service.cancel_deposit(
            user=request.user,
            transaction_id=transaction_id,
            cancellation_data=serializer.validated_data
        )

        if not result["success"]:
            return Response({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code")
            }, status=result.get("status_code", status.HTTP_400_BAD_REQUEST))

        logger.info(
            "deposit_cancelled",
            user_id=str(request.user.id),
            transaction_id=transaction_id,
            reason=serializer.validated_data.get("reason")
        )

        return Response({
            "success": True,
            "message": "Dépôt annulé avec succès",
            "transaction": TransactionSerializer(result["transaction"]).data,
            "refund_amount": result.get("refund_amount")
        }, status=status.HTTP_200_OK)


class ConfirmWithdrawalView(APIView):
    """
    POST /api/wallet/withdraw/{transaction_id}/confirm/
    Confirme un retrait (généralement appelé par admin ou système)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, transaction_id):
        serializer = TransactionConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "success": False,
                "error": "Données invalides",
                "details": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        result = wallet_service.confirm_withdrawal(
            user=request.user,
            transaction_id=transaction_id,
            confirmation_data=serializer.validated_data
        )

        if not result["success"]:
            return Response({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code")
            }, status=result.get("status_code", status.HTTP_400_BAD_REQUEST))

        logger.info(
            "withdrawal_confirmed",
            user_id=str(request.user.id),
            transaction_id=transaction_id,
            amount=result.get("amount")
        )

        return Response({
            "success": True,
            "message": "Retrait confirmé avec succès",
            "transaction": TransactionSerializer(result["transaction"]).data,
            "wallet_balance": result.get("wallet_balance"),
            "amount_debited": result.get("amount_debited")
        }, status=status.HTTP_200_OK)


class CancelWithdrawalView(APIView):
    """
    POST /api/wallet/withdraw/{transaction_id}/cancel/
    Annule un retrait en attente
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, transaction_id):
        serializer = TransactionCancelSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "success": False,
                "error": "Données invalides",
                "details": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        result = wallet_service.cancel_withdrawal(
            user=request.user,
            transaction_id=transaction_id,
            cancellation_data=serializer.validated_data
        )

        if not result["success"]:
            return Response({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code")
            }, status=result.get("status_code", status.HTTP_400_BAD_REQUEST))

        logger.info(
            "withdrawal_cancelled",
            user_id=str(request.user.id),
            transaction_id=transaction_id,
            reason=serializer.validated_data.get("reason")
        )

        return Response({
            "success": True,
            "message": "Retrait annulé avec succès",
            "transaction": TransactionSerializer(result["transaction"]).data,
            "refund_amount": result.get("refund_amount"),
            "wallet_balance": result.get("wallet_balance")
        }, status=status.HTTP_200_OK)


class TransactionStatusView(APIView):
    """
    GET /api/wallet/transactions/{transaction_id}/status/
    Vérifie le statut d'une transaction
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, transaction_id):
        try:
            # Récupération du wallet de l'utilisateur
            wallet = wallet_service.get_or_create_wallet(request.user)

            # Récupération de la transaction (sécurisée par wallet)
            transaction = wallet.transactions.get(id=transaction_id)

            # Vérification du statut auprès de Flutterwave si nécessaire
            flutterwave_status = None
            if transaction.flutterwave_transaction_id and transaction.status in ['pending', 'processing']:
                flutterwave_result = wallet_service.check_transaction_status(transaction)
                if flutterwave_result["success"]:
                    flutterwave_status = flutterwave_result["status"]

            serializer = TransactionSerializer(transaction)

            return Response({
                "success": True,
                "transaction": serializer.data,
                "flutterwave_status": flutterwave_status,
                "can_cancel": transaction.status in ['pending'],
                "can_confirm": transaction.status in ['processing'] and request.user.is_staff,
                "next_actions": self._get_next_actions(transaction, request.user)
            }, status=status.HTTP_200_OK)

        except Transaction.DoesNotExist:
            return Response({
                "success": False,
                "error": "Transaction non trouvée",
                "code": "transaction_not_found"
            }, status=status.HTTP_404_NOT_FOUND)

    def _get_next_actions(self, transaction, user):
        """Retourne les actions possibles pour cette transaction"""
        actions = []

        if transaction.status == 'pending':
            actions.append({
                "action": "cancel",
                "method": "POST",
                "endpoint": f"/api/wallet/{transaction.transaction_type}/{{transaction_id}}/cancel/",
                "description": f"Annuler ce {transaction.get_transaction_type_display()}"
            })

        if transaction.status == 'processing' and user.is_staff:
            actions.append({
                "action": "confirm",
                "method": "POST",
                "endpoint": f"/api/wallet/{transaction.transaction_type}/{{transaction_id}}/confirm/",
                "description": f"Confirmer ce {transaction.get_transaction_type_display()}"
            })

        return actions


class UpdateTransactionStatusView(APIView):
    """
    PATCH /api/wallet/transactions/{transaction_id}/status/
    Met à jour le statut d'une transaction (admin seulement)
    """
    permission_classes = [IsAuthenticated]
    # TODO: Ajouter permission IsAdminUser quand disponible

    def patch(self, request, transaction_id):
        # Vérification des permissions admin (temporaire)
        if not request.user.is_staff:
            return Response({
                "success": False,
                "error": "Permissions insuffisantes",
                "code": "insufficient_permissions"
            }, status=status.HTTP_403_FORBIDDEN)

        serializer = TransactionStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "success": False,
                "error": "Données invalides",
                "details": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        result = wallet_service.update_transaction_status(
            transaction_id=transaction_id,
            new_status=serializer.validated_data['status'],
            update_data=serializer.validated_data
        )

        if not result["success"]:
            return Response({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code")
            }, status=result.get("status_code", status.HTTP_400_BAD_REQUEST))

        logger.info(
            "transaction_status_updated",
            transaction_id=transaction_id,
            old_status=result.get("old_status"),
            new_status=serializer.validated_data['status'],
            updated_by=str(request.user.id)
        )

        return Response({
            "success": True,
            "message": "Statut de la transaction mis à jour avec succès",
            "transaction": TransactionSerializer(result["transaction"]).data,
            "old_status": result.get("old_status"),
            "new_status": serializer.validated_data['status']
        }, status=status.HTTP_200_OK)


class WalletStatsView(APIView):
    """
    GET /api/wallet/stats/
    Statistiques du portefeuille (admin seulement)
    """
    permission_classes = [IsAuthenticated]
    # TODO: Ajouter permission IsAdminUser quand disponible

    def get(self, request):
        # Vérification des permissions admin (temporaire)
        if not request.user.is_staff:
            return Response({
                "success": False,
                "error": "Permissions insuffisantes",
                "code": "insufficient_permissions"
            }, status=status.HTTP_403_FORBIDDEN)

        stats = wallet_service.get_wallet_statistics()

        return Response({
            "success": True,
            "stats": stats
        }, status=status.HTTP_200_OK)


class RetryTransactionView(APIView):
    """
    POST /api/wallet/transactions/{transaction_id}/retry/
    Réessaie une transaction échouée
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, transaction_id):
        try:
            wallet = wallet_service.get_or_create_wallet(request.user)
            transaction = wallet.transactions.get(id=transaction_id)

            # Vérifier que la transaction peut être relancée
            if transaction.status not in ['failed', 'cancelled']:
                return Response({
                    "success": False,
                    "error": f"Impossible de relancer une transaction {transaction.get_status_display()}",
                    "code": "invalid_status_for_retry"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Vérifier le statut auprès de Flutterwave
            if transaction.flutterwave_transaction_id:
                if transaction.transaction_type == 'deposit':
                    flutterwave_result = wallet_service.check_transaction_status(transaction)
                    if flutterwave_result.get("success") and flutterwave_result.get("status") == "completed":
                        # La transaction a réussi côté Flutterwave, on la confirme
                        if transaction.transaction_type == 'deposit':
                            result = wallet_service.confirm_deposit(request.user, transaction_id)
                        else:
                            result = wallet_service.confirm_withdrawal(request.user, transaction_id)
                        
                        if result["success"]:
                            return Response({
                                "success": True,
                                "message": "Transaction confirmée avec succès",
                                "transaction": TransactionSerializer(result["transaction"]).data
                            }, status=status.HTTP_200_OK)

            # Si on arrive ici, on doit relancer la transaction
            # Pour l'instant, on retourne une erreur car la relance nécessite les détails originaux
            return Response({
                "success": False,
                "error": "La relance automatique n'est pas encore implémentée. Veuillez créer une nouvelle transaction.",
                "code": "retry_not_implemented"
            }, status=status.HTTP_501_NOT_IMPLEMENTED)

        except Transaction.DoesNotExist:
            return Response({
                "success": False,
                "error": "Transaction non trouvée",
                "code": "transaction_not_found"
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error("transaction_retry_error", error=str(e), transaction_id=str(transaction_id))
            return Response({
                "success": False,
                "error": "Erreur lors de la relance",
                "code": "retry_error"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EstimateFeesView(APIView):
    """
    POST /api/wallet/fees/estimate/
    Estime les frais pour une transaction avant de l'initier
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Estime les frais pour un dépôt ou retrait
        
        Body:
        {
            "transaction_type": "deposit" | "withdrawal",
            "amount": 100.00,
            "payment_method": "card" | "orange_money",
            "currency": "EUR" (optionnel, utilise celui du wallet si absent)
        }
        """
        try:
            amount = float(request.data.get('amount', 0))
            transaction_type = request.data.get('transaction_type')
            payment_method = request.data.get('payment_method')
            
            if not all([amount, transaction_type, payment_method]):
                return Response({
                    "success": False,
                    "error": "amount, transaction_type et payment_method sont requis",
                    "code": "missing_parameters"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if transaction_type not in ['deposit', 'withdrawal']:
                return Response({
                    "success": False,
                    "error": "transaction_type doit être 'deposit' ou 'withdrawal'",
                    "code": "invalid_transaction_type"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Récupérer la devise du wallet
            wallet = wallet_service.get_or_create_wallet(request.user)
            currency = request.data.get('currency') or wallet.currency
            
            # Calculer les frais
            if transaction_type == 'deposit':
                fee = WalletService._calculate_deposit_fee(amount, payment_method, currency)
            else:
                fee = WalletService._calculate_withdrawal_fee(amount, payment_method, currency)
            
            total = amount + fee if transaction_type == 'deposit' else amount + fee
            
            return Response({
                "success": True,
                "estimation": {
                    "amount": amount,
                    "fee": float(fee),
                    "total": float(total),
                    "currency": currency,
                    "currency_info": {
                        "code": currency,
                        "symbol": WalletService._get_currency_symbol(currency),
                        "name": WalletService._get_currency_name(currency)
                    },
                    "transaction_type": transaction_type,
                    "payment_method": payment_method
                }
            }, status=status.HTTP_200_OK)

        except ValueError as e:
            return Response({
                "success": False,
                "error": "Montant invalide",
                "code": "invalid_amount"
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error("fee_estimation_error", error=str(e))
            return Response({
                "success": False,
                "error": "Erreur lors de l'estimation des frais",
                "code": "estimation_error"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)