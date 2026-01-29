from django.urls import path
from .Views.wallet_views import (
    WalletView,
    DepositView,
    WithdrawalView,
    TransactionListView,
    TransactionDetailView,
    FlutterwaveWebhookView,
    ConfirmDepositView,
    CancelDepositView,
    ConfirmWithdrawalView,
    CancelWithdrawalView,
    TransactionStatusView,
    UpdateTransactionStatusView,
    WalletStatsView,
    RetryTransactionView,
    EstimateFeesView
)
from .Views.payment_method_views import (
    PaymentMethodListView,
    PaymentMethodDetailView,
    PaymentMethodSetDefaultView
)

app_name = 'Wallet'

urlpatterns = [
    # Wallet principal
    path('', WalletView.as_view(), name='wallet'),

    # Transactions - Dépôts
    path('deposit/', DepositView.as_view(), name='deposit'),
    path('deposit/<uuid:transaction_id>/confirm/', ConfirmDepositView.as_view(), name='confirm_deposit'),
    path('deposit/<uuid:transaction_id>/cancel/', CancelDepositView.as_view(), name='cancel_deposit'),

    # Transactions - Retraits
    path('withdraw/', WithdrawalView.as_view(), name='withdraw'),
    path('withdraw/<uuid:transaction_id>/confirm/', ConfirmWithdrawalView.as_view(), name='confirm_withdrawal'),
    path('withdraw/<uuid:transaction_id>/cancel/', CancelWithdrawalView.as_view(), name='cancel_withdrawal'),

    # Liste et détail des transactions
    path('transactions/', TransactionListView.as_view(), name='transaction_list'),
    path('transactions/<uuid:transaction_id>/', TransactionDetailView.as_view(), name='transaction_detail'),
    path('transactions/<uuid:transaction_id>/status/', TransactionStatusView.as_view(), name='transaction_status'),
    path('transactions/<uuid:transaction_id>/retry/', RetryTransactionView.as_view(), name='retry_transaction'),

    # Utilitaires
    path('fees/estimate/', EstimateFeesView.as_view(), name='estimate_fees'),

    # Méthodes de paiement sauvegardées
    path('payment-methods/', PaymentMethodListView.as_view(), name='payment_method_list'),
    path('payment-methods/<uuid:payment_method_id>/', PaymentMethodDetailView.as_view(), name='payment_method_detail'),
    path('payment-methods/<uuid:payment_method_id>/set-default/', PaymentMethodSetDefaultView.as_view(), name='payment_method_set_default'),

    # Webhook Flutterwave
    path('webhook/', FlutterwaveWebhookView.as_view(), name='flutterwave_webhook'),

    # Admin (nécessite permissions)
    path('transactions/<uuid:transaction_id>/update-status/', UpdateTransactionStatusView.as_view(), name='update_transaction_status'),
    path('stats/', WalletStatsView.as_view(), name='wallet_stats'),
]