"""
URLs pour l'application wallet
"""
from django.urls import path
from .Views import (
    WalletView,
    WalletSummaryView,
    DepositInitiateView,
    DepositConfirmView,
    WithdrawalInitiateView,
    WithdrawalConfirmView,
    TransactionHistoryView,
    TransactionDetailView,
    PaymentProvidersView,
)

urlpatterns = [
    # Wallet
    path('', WalletView.as_view(), name='wallet-detail'),
    path('summary/', WalletSummaryView.as_view(), name='wallet-summary'),
    
    # Dépôts
    path('deposit/initiate/', DepositInitiateView.as_view(), name='deposit-initiate'),
    path('deposit/confirm/', DepositConfirmView.as_view(), name='deposit-confirm'),
    
    # Retraits
    path('withdraw/initiate/', WithdrawalInitiateView.as_view(), name='withdrawal-initiate'),
    path('withdraw/confirm/', WithdrawalConfirmView.as_view(), name='withdrawal-confirm'),
    
    # Transactions
    path('transactions/', TransactionHistoryView.as_view(), name='transaction-history'),
    path('transactions/<uuid:transaction_id>/', TransactionDetailView.as_view(), name='transaction-detail'),
    
    # Providers
    path('payment-providers/', PaymentProvidersView.as_view(), name='payment-providers'),
]