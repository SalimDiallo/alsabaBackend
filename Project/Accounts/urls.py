from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .Views.registerLogViews import PhoneAuthView, VerifyOTPView, AuthStatusView, ResendOTPView, LogoutView
from .Views.id_verificationViews import KYCVerifyView
from .Views.profile import ProfileView
from .Views.delete import AccountDeleteRequestView, AccountDeleteConfirmView
from .Views.didit_webhook_views import DiditWebhookView

app_name = 'Accounts'

urlpatterns = [
    # OTP avec Didit
    path('auth/phone/', PhoneAuthView.as_view(), name='phone_auth'),
    path('auth/verify/', VerifyOTPView.as_view(), name='verify_otp'),
    path('auth/resend/', ResendOTPView.as_view(), name='resend_otp'),
    path('auth/status/', AuthStatusView.as_view(), name='auth_status'),
    # JWT Token refresh / logout
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    # Profile User
    path('profile/', ProfileView.as_view(), name='user_profile'),
    #Didit KYC
    path('kyc/verify/', KYCVerifyView.as_view(), name='kyc_verify'),
    # Webhook Didit (KYC Asynchrone)
    path('webhooks/didit/kyc/', DiditWebhookView.as_view(), name='didit_webhook'),
    # Delete Account
    path('delete/', AccountDeleteRequestView.as_view(), name='account_delete_request'),
    path('delete/confirm/', AccountDeleteConfirmView.as_view(), name='account_delete_confirm'),

]
