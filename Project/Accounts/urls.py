from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    CheckPhoneNumberView,
    # DebugOTPView,
    UserProfileView,
    KYCVerificationView,
    KYCStatusView,
    DeleteAccountView,
    LogoutView,
    # PhoneAuthView,
    # VerifyOTPView,
    DiditWebhookView,
)
from .Views.registerLogViews import PhoneAuthView, VerifyOTPView, AuthStatusView, ResendOTPView
app_name = 'Accounts'

urlpatterns = [
    # Endpoints publics (sans authentification)
    path('check-phone/', CheckPhoneNumberView.as_view(), name='check-phone'),# Marche
    # Endpoints protégés (nécessitent JWT)
    path('profile/', UserProfileView.as_view(), name='profile'),# Marche
    path('kyc/submit/', KYCVerificationView.as_view(), name='kyc-submit'),
    path('kyc/status/', KYCStatusView.as_view(), name='kyc-status'),
    #path('logout/', LogoutView.as_view(), name='logout'),
    path('delete-account/', DeleteAccountView.as_view(), name='delete-account'),
    # POUR L'AUTHENTIFICATION PAR TÉLÉPHONE ET OTP
    # path('auth/', PhoneAuthView.as_view(), name='phone-auth'),# Marche
    # path('verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),# Marche
    #path('debug/otps/', DebugOTPView.as_view(), name='debug-otps'),# Marche
    #Didit KYC
    path("kyc/", KYCVerificationView.as_view(), name="kyc-submit"),
    path("kyc/status/", KYCStatusView.as_view(), name="kyc-status"),
    path("webhook/didit/", DiditWebhookView.as_view(), name="didit-webhook"),
    # OTP avec Didit
    path('auth/phone/', PhoneAuthView.as_view(), name='phone_auth'),
    path('auth/verify/', VerifyOTPView.as_view(), name='verify_otp'),
    path('auth/resend/', ResendOTPView.as_view(), name='resend_otp'),
    path('auth/status/', AuthStatusView.as_view(), name='auth_status'),
]
