from django.urls import path
from .Views.walletView import WalletDetailView
from .Views.deposit import DepositView
from .Views.withdrawal import WithdrawalView
urlpatterns = [
    path('', WalletDetailView.as_view(), name='wallet_detail'),
    path('deposit/', DepositView.as_view(), name='wallet_deposit'),
    path('withdraw/', WithdrawalView.as_view(), name='wallet_withdraw'),
]