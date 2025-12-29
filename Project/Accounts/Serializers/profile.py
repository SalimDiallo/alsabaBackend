# apps/auth/Serializers/OTP_serializers.py (ou profile_serializers.py)

from rest_framework import serializers
from ..models import User

class ProfileSerializer(serializers.ModelSerializer):
    """
    Serializer complet pour afficher le profil de l'utilisateur connecté
    """
    kyc_status_display = serializers.CharField(
        source='get_kyc_status_display',
        read_only=True
    )

    phone_verified_display = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'full_phone_number',
            'country_code',
            'phone_number',
            'phone_verified',
            'phone_verified_display',
            'phone_verified_at',

            # Infos personnelles
            'first_name',
            'last_name',
            'email',

            # KYC
            'kyc_status',
            'kyc_status_display',
            'kyc_verified_at',
            'kyc_submitted_at',
            'kyc_retry_count',

            # Données extraites par Didit (si KYC verified)
            'kyc_document_type',
            'kyc_document_number',
            'kyc_date_of_birth',
            'kyc_expiration_date',
            'kyc_gender',
            'kyc_nationality',
            'kyc_place_of_birth',
            'kyc_address',

            # Métadonnées compte
            'date_joined',
            'last_login',
            'is_active',
        ]
        read_only_fields = fields  # Tout en lecture seule

    def get_phone_verified_display(self, obj):
        return "Vérifié" if obj.phone_verified else "Non vérifié"