from rest_framework import serializers
from .models import Offer, Dispute
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

    @staticmethod
    def setup_eager_loading(queryset):
        """ Optimization to avoid N+1 queries """
        queryset = queryset.select_related('user', 'accepted_by')
        return queryset

    class Meta:
        model = Offer
        fields = [
            'id', 'user', 'amount_sell', 'currency_sell', 
            'amount_buy', 'currency_buy', 'rate', 
            'status', 'created_at', 'expires_at',
            'accepted_by', 'accepted_at',
            'b1_confirmed', 'b2_confirmed'
        ]
        read_only_fields = ['id', 'user', 'rate', 'status', 'created_at', 'expires_at', 'accepted_by', 'accepted_at', 'b1_confirmed', 'b2_confirmed']

class CreateOfferSerializer(serializers.Serializer):
    amount_sell = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    currency_sell = serializers.CharField(max_length=3)
    amount_buy = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    currency_buy = serializers.CharField(max_length=3)
    expiry_hours = serializers.IntegerField(default=24, min_value=1, max_value=72)
    # Beneficiary data (optional for creation)
    beneficiary_name = serializers.CharField(required=False)
    beneficiary_phone = serializers.CharField(required=False)

    def validate(self, data):
        """
        Global offer validation including exchange rate.
        """
        from .exchange_service import ExchangeRateService
        from decimal import Decimal

        currency_sell = data.get('currency_sell')
        currency_buy = data.get('currency_buy')
        amount_sell = data.get('amount_sell')
        amount_buy = data.get('amount_buy')

        if currency_sell == currency_buy:
            raise serializers.ValidationError({
                "currency_buy": "The buy currency must be different from the sell currency."
            })
        
        if amount_sell <= 0 or amount_buy <= 0:
             raise serializers.ValidationError("Amounts must be greater than zero.")

        # Market rate verification
        market_rate = ExchangeRateService.get_rate(currency_sell, currency_buy)
        if market_rate:
            market_rate = Decimal(str(market_rate))
            user_rate = amount_buy / amount_sell
            
            # Percentage deviation calculation
            deviation = abs((user_rate - market_rate) / market_rate) * 100
            
            # If deviation is greater than 15%, block (anti-error/fraud security)
            if deviation > 15:
                logger.warning("offer_rate_deviation_too_high", 
                               user_rate=float(user_rate), 
                               market_rate=float(market_rate), 
                               deviation=float(deviation))
                raise serializers.ValidationError(
                    f"The proposed rate ({user_rate:.4f}) deviates too much from the market rate ({market_rate:.4f}). "
                    f"The maximum allowed deviation is 15%."
                )
             
        return data

class AcceptOfferSerializer(serializers.Serializer):
    offer_id = serializers.UUIDField()
    # Beneficiary for the buyer (the one who will receive the funds sold by A1)
    beneficiary_name = serializers.CharField(required=False)
    beneficiary_phone = serializers.CharField(required=False)

class UpdateOfferSerializer(serializers.Serializer):
    amount_sell = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1, required=False)
    currency_sell = serializers.CharField(max_length=3, required=False)
    amount_buy = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1, required=False)
    currency_buy = serializers.CharField(max_length=3, required=False)

class ValidateOfferSerializer(serializers.Serializer):
    offer_id = serializers.UUIDField()
    # Beneficiary for the seller (A1)
    beneficiary_name = serializers.CharField(required=False)
    beneficiary_phone = serializers.CharField(required=False)

class DisputeOfferSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)

# Serializers for disputes
class DisputeSerializer(serializers.ModelSerializer):
    """Serializer to display a dispute"""
    initiated_by = UserMinimalSerializer(read_only=True)
    reviewed_by = UserMinimalSerializer(read_only=True)
    
    class Meta:
        model = Dispute
        fields = [
            'id', 'offer', 'initiated_by', 'reason', 'evidence',
            'status', 'resolution', 'reviewed_by', 'admin_notes',
            'created_at', 'updated_at', 'reviewed_at', 'resolved_at'
        ]
        read_only_fields = [
            'id', 'initiated_by', 'status', 'resolution',
            'reviewed_by', 'admin_notes', 'created_at',
            'updated_at', 'reviewed_at', 'resolved_at'
        ]


class InitiateDisputeSerializer(serializers.Serializer):
    """Serializer to initiate a dispute"""
    reason = serializers.CharField(max_length=500)
    evidence = serializers.JSONField(required=False, default=dict)
    
    def validate_reason(self, value):
        if len(value.strip()) < 10:
            raise serializers.ValidationError("The reason must contain at least 10 characters")
        return value


class ResolveDisputeSerializer(serializers.Serializer):
    """Serializer to resolve a dispute (Admin only)"""
    RESOLUTION_CHOICES = [
        ('refund_a1', 'Refund A1'),
        ('refund_a2', 'Refund A2'),
        ('split', 'Split 50/50'),
    ]
    
    resolution = serializers.ChoiceField(choices=RESOLUTION_CHOICES)
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)