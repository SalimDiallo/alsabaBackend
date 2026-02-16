from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.utils import timezone
from django.db.models import Q
from decimal import Decimal
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
    TransactionStatusUpdateSerializer,
    EstimateFeesSerializer, # Added
)

from Project.idempotency import idempotent_endpoint
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, inline_serializer
from rest_framework import serializers

logger = structlog.get_logger(__name__)


class WalletView(APIView):
    """
    GET /api/wallet/
    Retrieves user wallet information
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get wallet",
        description="Returns information about the connected user's wallet (balance, currency, recent transactions).",
        tags=['Wallet'],
        responses={
            200: inline_serializer(
                name='WalletResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'wallet': WalletSerializer()
                }
            )
        }
    )
    def get(self, request):
        wallet = wallet_service.get_or_create_wallet(request.user)
        serializer = WalletSerializer(wallet)
        
        logger.info("wallet_viewed", user_id=str(request.user.id), balance=wallet.balance)

        return Response({
            "success": True,
            "wallet": serializer.data
        }, status=status.HTTP_200_OK)


class DepositView(APIView):
    """
    POST /api/wallet/deposit/
    Initiates a deposit to the wallet
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = 'deposit'

    @extend_schema(
        summary="Initiate a deposit",
        description="Initiates a deposit transaction via Flutterwave. Returns a payment link (v3) or redirection instructions.",
        request=DepositSerializer,
        tags=['Wallet'],
        responses={
            201: inline_serializer(
                name='DepositResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'message': serializers.CharField(),
                    'transaction': TransactionSerializer(),
                    'payment_link': serializers.URLField(),
                    'reference': serializers.CharField(),
                    'amount': serializers.FloatField(),
                    'fee': serializers.FloatField(),
                    'total': serializers.FloatField(),
                    'currency': serializers.CharField(),
                    'currency_info': serializers.JSONField(),
                    'expires_in': serializers.IntegerField()
                }
            ),
            400: inline_serializer(
                name='DepositError',
                fields={
                    'success': serializers.BooleanField(),
                    'error': serializers.CharField(),
                    'code': serializers.CharField(required=False),
                    'available_balance': serializers.FloatField(required=False)
                }
            ),
            429: {"description": "Rate limit reached (throttle)"}
        }
    )
    @idempotent_endpoint()
    def post(self, request):
        serializer = DepositSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            logger.warning(
                "deposit_validation_failed",
                user_id=str(request.user.id),
                errors=serializer.errors
            )
            return Response({
                "success": False,
                "error": "Invalid data",
                "details": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        # Secure extraction of metadata (real IP, Agent, etc.)
        request_meta = auth_utils.extract_request_metadata(request)

        # Card details extraction if method is card and no payment_method_id
        card_details = None
        validated_data = serializer.validated_data
        payment_method_id = validated_data.get('payment_method_id')
        card_token = validated_data.get('card_token')
        
        if validated_data['payment_method'] == 'card':
            # 1. If payment_method_id provided, we only need the CVV
            if payment_method_id:
                if not validated_data.get('card_cvv'):
                    return Response({
                        "success": False,
                        "error": "CVV required even with a saved method",
                        "code": "cvv_required"
                    }, status=status.HTTP_400_BAD_REQUEST)
                card_details = {
                    'cvv': validated_data['card_cvv']
                }
            # 2. If card_token provided (PCI-DSS)
            elif card_token:
                # No card details needed, token is enough
                pass
            # 3. Otherwise, full details required
            else:
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
            payment_method_label=validated_data.get('payment_method_label'),
            redirect_url=validated_data.get('redirect_url'),
            card_token=card_token
        )

        if not result["success"]:
            return Response({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code"),
                "available_balance": result.get("available_balance")
            }, status=result.get("status_code", status.HTTP_400_BAD_REQUEST))

        # Transaction serialization
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
            "message": "Deposit initiated successfully",
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
    Initiates a withdrawal from the wallet
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = 'withdrawal'

    @extend_schema(
        summary="Initiate a withdrawal",
        description="Initiates a withdrawal transaction from the wallet to a bank account or mobile money via Flutterwave.",
        request=WithdrawalSerializer,
        tags=['Wallet'],
        responses={
            201: inline_serializer(
                name='WithdrawalResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'message': serializers.CharField(),
                    'transaction': TransactionSerializer(),
                    'reference': serializers.CharField(),
                    'amount': serializers.FloatField(),
                    'fee': serializers.FloatField(),
                    'total_deducted': serializers.FloatField(),
                    'currency': serializers.CharField(),
                    'currency_info': serializers.JSONField()
                }
            ),
            400: inline_serializer(
                name='WithdrawalError',
                fields={
                    'success': serializers.BooleanField(),
                    'error': serializers.CharField(),
                    'code': serializers.CharField(required=False),
                    'available_balance': serializers.FloatField(required=False),
                    'required_amount': serializers.FloatField(required=False)
                }
            ),
            429: {"description": "Limite de taux atteinte (throttle)"}
        }
    )
    @idempotent_endpoint()
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
                "error": "Invalid data",
                "details": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        # Account details preparation according to the method
        validated_data = serializer.validated_data
        payment_method = validated_data['payment_method']
        payment_method_id = validated_data.get('payment_method_id')
        
        # If payment_method_id provided, account_details will be built in wallet_service
        account_details = None
        if not payment_method_id:
            if payment_method == 'card':
                # Withdrawal to bank account
                account_details = {
                    'account_number': validated_data['account_number'],
                    'bank_code': validated_data['bank_code'],
                    'account_name': validated_data.get('account_name') or f"{request.user.first_name} {request.user.last_name}".strip() or request.user.full_phone_number,
                    'bank_name': validated_data.get('bank_name'),
                    'bank_country': validated_data.get('bank_country'),
                    'type': 'bank_account'  # Default type
                }
            elif payment_method == 'orange_money':
                account_details = {
                    'phone_number': validated_data['orange_money_number'],
                    'beneficiary_name': f"{request.user.first_name} {request.user.last_name}".strip() or request.user.full_phone_number
                }

        # Secure extraction of metadata (real IP, Agent, etc.)
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

        # Transaction serialization
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
            "message": "Withdrawal initiated successfully",
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
    Lists user transactions with filtering
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="List transactions",
        description="Lists transaction history with filtering and pagination.",
        tags=['Wallet'],
        parameters=[
            OpenApiParameter(name='transaction_type', type=OpenApiTypes.STR, enum=['deposit', 'withdrawal'], required=False),
            OpenApiParameter(name='status', type=OpenApiTypes.STR, enum=['pending', 'processing', 'completed', 'failed', 'cancelled'], required=False),
            OpenApiParameter(name='payment_method', type=OpenApiTypes.STR, enum=['card', 'orange_money'], required=False),
            OpenApiParameter(name='date_from', type=OpenApiTypes.DATE, required=False),
            OpenApiParameter(name='date_to', type=OpenApiTypes.DATE, required=False),
            OpenApiParameter(name='limit', type=OpenApiTypes.INT, required=False, default=20),
            OpenApiParameter(name='offset', type=OpenApiTypes.INT, required=False, default=0),
        ],
        responses={200: TransactionSerializer(many=True)}
    )
    def get(self, request):
        # Filtering parameters validation
        filter_serializer = TransactionListSerializer(data=request.query_params)
        if not filter_serializer.is_valid():
            return Response({
                "success": False,
                "error": "Invalid filtering parameters",
                "details": filter_serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        filters = filter_serializer.validated_data

        # Wallet retrieval
        wallet = wallet_service.get_or_create_wallet(request.user)

        # Query construction with N+1 optimization
        queryset = wallet.transactions.all().select_related('wallet', 'payment_method_saved')

        # Filters application
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

        # Serialization
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
    Detail of a specific transaction
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Transaction detail",
        description="Retrieves details of a specific transaction by ID.",
        tags=['Wallet'],
        responses={
            200: TransactionSerializer,
            404: {"description": "Transaction not found"}
        }
    )
    def get(self, request, transaction_id):
        try:
            # Retrieve user wallet
            wallet = wallet_service.get_or_create_wallet(request.user)

            # Retrieve transaction (secured by wallet)
            transaction = wallet.transactions.get(id=transaction_id)

            serializer = TransactionSerializer(transaction)

            return Response({
                "success": True,
                "transaction": serializer.data
            }, status=status.HTTP_200_OK)

        except Transaction.DoesNotExist:
            return Response({
                "success": False,
                "error": "Transaction not found",
                "code": "transaction_not_found"
            }, status=status.HTTP_404_NOT_FOUND)


class FlutterwaveWebhookView(APIView):
    """
    POST /api/wallet/webhook/
    Webhook for receiving Flutterwave notifications
    """
    permission_classes = []  # No authentication for webhooks

    @extend_schema(
        summary="Flutterwave Webhook",
        description="Endpoint for receiving asynchronous payment notifications from Flutterwave.",
        tags=['Wallet'],
        responses={200: {"description": "Webhook received"}},
        request=None
    )
    def post(self, request):
        """
        Processes Flutterwave webhooks with signature verification
        """
        try:
            # Retrieve signature from headers
            signature = request.META.get('HTTP_X_FLUTTERWAVE_SIGNATURE') or \
                       request.META.get('HTTP_SIGNATURE') or \
                       request.META.get('HTTP_X_VERIFY_HASH')
            raw_body = request.body
            from Wallet.Services.flutterwave.base import FlutterwaveBaseService
            base_service = FlutterwaveBaseService()
            if not base_service.webhook_secret:
                logger.error("flutterwave_webhook_secret_missing")
                return Response({"status": "error", "message": "Webhook secret not configured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            if not signature:
                logger.warning("webhook_signature_missing")
                return Response({"status": "error", "message": "Signature required"}, status=status.HTTP_401_UNAUTHORIZED)
            if not base_service.verify_webhook_signature(raw_body, signature):
                logger.warning(
                    "webhook_signature_invalid",
                    signature_provided=signature[:20] + "..." if signature else None
                )
                return Response(
                    {"status": "error", "message": "Invalid signature"},
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
                return Response({"status": "success", "message": result.get("message")}, status=status.HTTP_200_OK)
            else:
                return Response({"status": "error", "message": result.get("error")}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error("flutterwave_webhook_processing_error", error=str(e))
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ConfirmDepositView(APIView):
    """
    POST /api/wallet/deposit/{transaction_id}/confirm/
    Confirms a deposit (usually called by webhook or admin)
    """
    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="Confirm a deposit (Admin)",
        description="Manually confirms a deposit.",
        request=TransactionConfirmSerializer,
        tags=['Wallet'],
        responses={
            200: inline_serializer(
                name='ConfirmDepositResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'message': serializers.CharField(),
                    'transaction': TransactionSerializer(),
                    'wallet_balance': serializers.FloatField(),
                    'amount_credited': serializers.FloatField()
                }
            ),
            400: inline_serializer(
                name='ConfirmDepositError',
                fields={
                    'success': serializers.BooleanField(),
                    'error': serializers.CharField(),
                    'code': serializers.CharField()
                }
            )
        }
    )
    def post(self, request, transaction_id):
        serializer = TransactionConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "success": False,
                "error": "Invalid data",
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
            "message": "Deposit confirmed successfully",
            "transaction": TransactionSerializer(result["transaction"]).data,
            "wallet_balance": result.get("wallet_balance"),
            "amount_credited": result.get("amount_credited")
        }, status=status.HTTP_200_OK)


class CancelDepositView(APIView):
    """
    POST /api/wallet/deposit/{transaction_id}/cancel/
    Cancels a pending deposit
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Cancel a deposit",
        description="Cancels a pending deposit.",
        request=TransactionCancelSerializer,
        tags=['Wallet'],
        responses={
            200: inline_serializer(
                name='CancelDepositResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'message': serializers.CharField(),
                    'transaction': TransactionSerializer(),
                    'refund_amount': serializers.FloatField()
                }
            ),
            400: inline_serializer(
                name='CancelDepositError',
                fields={
                    'success': serializers.BooleanField(),
                    'error': serializers.CharField(),
                    'code': serializers.CharField()
                }
            )
        }
    )
    def post(self, request, transaction_id):
        serializer = TransactionCancelSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "success": False,
                "error": "Invalid data",
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
            "message": "Deposit cancelled successfully",
            "transaction": TransactionSerializer(result["transaction"]).data,
            "refund_amount": result.get("refund_amount")
        }, status=status.HTTP_200_OK)


class ConfirmWithdrawalView(APIView):
    """
    POST /api/wallet/withdraw/{transaction_id}/confirm/
    Confirms a withdrawal (usually called by admin or system)
    """
    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="Confirm a withdrawal (Admin)",
        description="Manually confirms a withdrawal.",
        request=TransactionConfirmSerializer,
        tags=['Wallet'],
        responses={200: TransactionSerializer}
    )
    def post(self, request, transaction_id):
        serializer = TransactionConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "success": False,
                "error": "Invalid data",
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
            "message": "Withdrawal confirmed successfully",
            "transaction": TransactionSerializer(result["transaction"]).data,
            "wallet_balance": result.get("wallet_balance"),
            "amount_debited": result.get("amount_debited")
        }, status=status.HTTP_200_OK)


class CancelWithdrawalView(APIView):
    """
    POST /api/wallet/withdraw/{transaction_id}/cancel/
    Cancels a pending withdrawal
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Cancel a withdrawal",
        description="Cancels a pending withdrawal. Refunds the amount to the wallet.",
        request=TransactionCancelSerializer,
        tags=['Wallet'],
        responses={200: TransactionSerializer}
    )
    def post(self, request, transaction_id):
        serializer = TransactionCancelSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "success": False,
                "error": "Invalid data",
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
            "message": "Withdrawal cancelled successfully",
            "transaction": TransactionSerializer(result["transaction"]).data,
            "refund_amount": result.get("refund_amount"),
            "wallet_balance": result.get("wallet_balance")
        }, status=status.HTTP_200_OK)


class TransactionStatusView(APIView):
    """
    GET /api/wallet/transactions/{transaction_id}/status/
    Checks transaction status
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Check transaction status",
        description="Checks the status (local and distant Flutterwave) of a transaction.",
        tags=['Wallet'],
        responses={
             200: inline_serializer(
                name='TransactionStatusResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'transaction': TransactionSerializer(),
                    'flutterwave_status': serializers.CharField(),
                    'can_cancel': serializers.BooleanField(),
                    'can_confirm': serializers.BooleanField(),
                    'next_actions': serializers.ListField()
                }
             )
        }
    )
    def get(self, request, transaction_id):
        try:
            # Retrieve user wallet
            wallet = wallet_service.get_or_create_wallet(request.user)

            # Retrieve transaction (secured by wallet)
            transaction = wallet.transactions.get(id=transaction_id)

            # Status check with Flutterwave if necessary
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
                "error": "Transaction not found",
                "code": "transaction_not_found"
            }, status=status.HTTP_404_NOT_FOUND)

    def _get_next_actions(self, transaction, user):
        """Returns the possible actions for this transaction"""
        actions = []

        if transaction.status == 'pending':
            actions.append({
                "action": "cancel",
                "method": "POST",
                "endpoint": f"/api/wallet/{transaction.transaction_type}/{{transaction_id}}/cancel/",
                "description": f"Cancel this {transaction.get_transaction_type_display()}"
            })

        if transaction.status == 'processing' and user.is_staff:
            actions.append({
                "action": "confirm",
                "method": "POST",
                "endpoint": f"/api/wallet/{transaction.transaction_type}/{{transaction_id}}/confirm/",
                "description": f"Confirm this {transaction.get_transaction_type_display()}"
            })

        return actions


class UpdateTransactionStatusView(APIView):
    """
    PATCH /api/wallet/transactions/{transaction_id}/status/
    Updates the status of a transaction (admin only)
    """
    permission_classes = [IsAdminUser]
    
    @extend_schema(
        summary="Update transaction status (Admin)",
        description="Forces the status update of a transaction.",
        request=TransactionStatusUpdateSerializer,
        tags=['Wallet'],
        responses={200: TransactionSerializer}
    )
    def patch(self, request, transaction_id):

        serializer = TransactionStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "success": False,
                "error": "Invalid data",
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
            "message": "Transaction status updated successfully",
            "transaction": TransactionSerializer(result["transaction"]).data,
            "old_status": result.get("old_status"),
            "new_status": serializer.validated_data['status']
        }, status=status.HTTP_200_OK)


class WalletStatsView(APIView):
    """
    GET /api/wallet/stats/
    Wallet statistics (admin only)
    """
    permission_classes = [IsAdminUser]
    
    @extend_schema(
        summary="Wallet statistics (Admin)",
        description="Returns global statistics about wallets.",
        tags=['Wallet'],
        responses={200: OpenApiTypes.OBJECT}
    )
    def get(self, request):

        stats = wallet_service.get_wallet_statistics()

        return Response({
            "success": True,
            "stats": stats
        }, status=status.HTTP_200_OK)


class RetryTransactionView(APIView):
    """
    POST /api/wallet/transactions/{transaction_id}/retry/
    Retries a failed transaction
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TransactionSerializer

    @extend_schema(
        summary="Retry a failed transaction",
        description="Attempts to relaunch or confirm a transaction marked as failed or cancelled.",
        tags=['Wallet'],
        request=None,
        responses={
            200: TransactionSerializer,
            501: {"description": "Not implemented"}
        }
    )
    def post(self, request, transaction_id):
        try:
            wallet = wallet_service.get_or_create_wallet(request.user)
            transaction = wallet.transactions.get(id=transaction_id)

            # Verify that the transaction can be retried
            if transaction.status not in ['failed', 'cancelled']:
                return Response({
                    "success": False,
                    "error": f"Cannot retry a {transaction.get_status_display()} transaction",
                    "code": "invalid_status_for_retry"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Verify status with Flutterwave
            if transaction.flutterwave_transaction_id:
                if transaction.transaction_type == 'deposit':
                    flutterwave_result = wallet_service.check_transaction_status(transaction)
                    if flutterwave_result.get("success") and flutterwave_result.get("status") == "completed":
                        # The transaction succeeded on the Flutterwave side, we confirm it
                        if transaction.transaction_type == 'deposit':
                            result = wallet_service.confirm_deposit(request.user, transaction_id)
                        else:
                            result = wallet_service.confirm_withdrawal(request.user, transaction_id)
                        
                        if result["success"]:
                            return Response({
                                "success": True,
                                "message": "Transaction confirmed successfully",
                                "transaction": TransactionSerializer(result["transaction"]).data
                            }, status=status.HTTP_200_OK)

            # If we reach here, we must relaunch the transaction
            # For now, we return an error because relaunch requires the original details
            return Response({
                "success": False,
                "error": "Automatic retry is not yet implemented. Please create a new transaction.",
                "code": "retry_not_implemented"
            }, status=status.HTTP_501_NOT_IMPLEMENTED)

        except Transaction.DoesNotExist:
            return Response({
                "success": False,
                "error": "Transaction not found",
                "code": "transaction_not_found"
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error("transaction_retry_error", error=str(e), transaction_id=str(transaction_id))
            return Response({
                "success": False,
                "error": "Error during retry",
                "code": "retry_error"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EstimateFeesView(APIView):
    """
    POST /api/wallet/fees/estimate/
    Estimates fees for a transaction before initiating it
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Estimate fees",
        description="Calculates estimated fees for a given transaction.",
        tags=['Wallet'],
        request=inline_serializer(
            name='EstimateFeesRequest',
            fields={
                'transaction_type': serializers.ChoiceField(choices=['deposit', 'withdrawal']),
                'amount': serializers.DecimalField(max_digits=12, decimal_places=2),
                'payment_method': serializers.ChoiceField(choices=['card', 'orange_money']),
                'currency': serializers.CharField(required=False)
            }
        ),
        responses={
            200: inline_serializer(
                name='EstimateFeesResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'estimation': inline_serializer(
                        name='FeesEstimationDetail',
                        fields={
                            'amount': serializers.FloatField(),
                            'fee': serializers.FloatField(),
                            'total': serializers.FloatField(),
                            'currency': serializers.CharField(),
                            'currency_info': serializers.JSONField(),
                            'transaction_type': serializers.CharField(),
                            'payment_method': serializers.CharField()
                        }
                    )
                }
            ),
            400: inline_serializer(
                name='EstimateFeesError',
                fields={
                    'success': serializers.BooleanField(),
                    'error': serializers.CharField(),
                    'code': serializers.CharField()
                }
            )
        }
    )
    def post(self, request):
        """
        Estimates fees for a deposit or withdrawal
        
        Body:
        {
            "transaction_type": "deposit" | "withdrawal",
            "amount": 100.00,
            "payment_method": "card" | "orange_money",
            "currency": "EUR" (optional, uses the wallet's if absent)
        }
        """
        try:
            amount = Decimal(str(request.data.get('amount', 0)))
            transaction_type = request.data.get('transaction_type')
            payment_method = request.data.get('payment_method')
            
            if not all([amount, transaction_type, payment_method]):
                return Response({
                    "success": False,
                    "error": "amount, transaction_type and payment_method are required",
                    "code": "missing_parameters"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if transaction_type not in ['deposit', 'withdrawal']:
                return Response({
                    "success": False,
                    "error": "transaction_type must be 'deposit' or 'withdrawal'",
                    "code": "invalid_transaction_type"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Retrieve wallet currency
            wallet = wallet_service.get_or_create_wallet(request.user)
            currency = request.data.get('currency') or wallet.currency
            
            # Calculate fees
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
                "error": "Invalid amount",
                "code": "invalid_amount"
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error("fee_estimation_error", error=str(e))
            return Response({
                "success": False,
                "error": "Error during fee estimation",
                "code": "estimation_error"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)