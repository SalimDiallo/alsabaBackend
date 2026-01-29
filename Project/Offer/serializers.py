from rest_framework import serializers
from .models import Offer, EscrowLock
from Accounts.models import User

class UserMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'country_code', 'kyc_status', 'kyc_nationality']

class OfferSerializer(serializers.ModelSerializer):
    user = UserMinimalSerializer(read_only=True)
    accepted_by = UserMinimalSerializer(read_only=True)
    amount_sell = serializers.FloatField(read_only=True)
    amount_buy = serializers.FloatField(read_only=True)

    class Meta:
        model = Offer
        fields = [
            'id', 'user', 'amount_sell', 'currency_sell', 
            'amount_buy', 'currency_buy', 'rate', 
            'status', 'created_at', 'expires_at',
            'accepted_by', 'accepted_at'
        ]
        read_only_fields = ['id', 'user', 'rate', 'status', 'created_at', 'expires_at', 'accepted_by', 'accepted_at']

class CreateOfferSerializer(serializers.Serializer):
    amount_sell = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    currency_sell = serializers.CharField(max_length=3)
    amount_buy = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    currency_buy = serializers.CharField(max_length=3)
    expiry_hours = serializers.IntegerField(default=24, min_value=1, max_value=72)
    # Beneficiary data (optionnel pour la création)
    beneficiary_name = serializers.CharField(required=False)
    beneficiary_phone = serializers.CharField(required=False)

class AcceptOfferSerializer(serializers.Serializer):
    offer_id = serializers.UUIDField()
    # Beneficiary pour l'acheteur (celui qui recevra les fonds vendus par A1)
    beneficiary_name = serializers.CharField(required=False)
    beneficiary_phone = serializers.CharField(required=False)

class DisputeOfferSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)
