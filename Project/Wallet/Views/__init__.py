"""
Importations des vues pour faciliter l'accès
"""
from .wallet_views import WalletView, WalletSummaryView
from .deposit_views import DepositInitiateView, DepositConfirmView
from .withdrawal_views import WithdrawalInitiateView, WithdrawalConfirmView
from .transaction_views import TransactionHistoryView, TransactionDetailView
from .provider_views import PaymentProvidersView

__all__ = [
    'WalletView',
    'WalletSummaryView',
    'DepositInitiateView',
    'DepositConfirmView',
    'WithdrawalInitiateView',
    'WithdrawalConfirmView',
    'TransactionHistoryView',
    'TransactionDetailView',
    'PaymentProvidersView',
]