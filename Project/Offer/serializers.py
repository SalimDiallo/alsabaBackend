from rest_framework import serializers
from .models import Offer, EscrowLock, Dispute
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
        """ Optimisation pour éviter les requêtes N+1 """
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
    # Beneficiary data (optionnel pour la création)
    beneficiary_name = serializers.CharField(required=False)
    beneficiary_phone = serializers.CharField(required=False)

    def validate(self, data):
        """
        Validation globale de l'offre incluant le taux de change.
        """
        from .exchange_service import ExchangeRateService
        from decimal import Decimal

        currency_sell = data.get('currency_sell')
        currency_buy = data.get('currency_buy')
        amount_sell = data.get('amount_sell')
        amount_buy = data.get('amount_buy')

        if currency_sell == currency_buy:
            raise serializers.ValidationError({
                "currency_buy": "La devise d'achat doit être différente de la devise de vente."
            })
        
        if amount_sell <= 0 or amount_buy <= 0:
             raise serializers.ValidationError("Les montants doivent être supérieurs à zéro.")

        # Vérification du taux par rapport au marché
        market_rate = ExchangeRateService.get_rate(currency_sell, currency_buy)
        if market_rate:
            market_rate = Decimal(str(market_rate))
            user_rate = amount_buy / amount_sell
            
            # Calcul de l'écart en pourcentage
            deviation = abs((user_rate - market_rate) / market_rate) * 100
            
            # Si l'écart est supérieur à 15%, on bloque (sécurité anti-erreur/fraude)
            if deviation > 15:
                logger.warning("offer_rate_deviation_too_high", 
                               user_rate=float(user_rate), 
                               market_rate=float(market_rate), 
                               deviation=float(deviation))
                raise serializers.ValidationError(
                    f"Le taux proposé ({user_rate:.4f}) s'éloigne trop du taux du marché ({market_rate:.4f}). "
                    f"L'écart maximum autorisé est de 15%."
                )
             
        return data

class AcceptOfferSerializer(serializers.Serializer):
    offer_id = serializers.UUIDField()
    # Beneficiary pour l'acheteur (celui qui recevra les fonds vendus par A1)
    beneficiary_name = serializers.CharField(required=False)
    beneficiary_phone = serializers.CharField(required=False)

class UpdateOfferSerializer(serializers.Serializer):
    amount_sell = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1, required=False)
    currency_sell = serializers.CharField(max_length=3, required=False)
    amount_buy = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1, required=False)
    currency_buy = serializers.CharField(max_length=3, required=False)

class ValidateOfferSerializer(serializers.Serializer):
    offer_id = serializers.UUIDField()
    # Beneficiary pour le vendeur (A1)
    beneficiary_name = serializers.CharField(required=False)
    beneficiary_phone = serializers.CharField(required=False)

class DisputeOfferSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)

# ✅ NOUVEAU: Serializers pour les litiges
class DisputeSerializer(serializers.ModelSerializer):
    """Sérializer pour afficher un litige"""
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
    """Sérializer pour initier un litige"""
    reason = serializers.CharField(max_length=500)
    evidence = serializers.JSONField(required=False, default=dict)
    
    def validate_reason(self, value):
        if len(value.strip()) < 10:
            raise serializers.ValidationError("La raison doit contenir au moins 10 caractères")
        return value


class ResolveDisputeSerializer(serializers.Serializer):
    """Sérializer pour résoudre un litige (Admin only)"""
    RESOLUTION_CHOICES = [
        ('refund_a1', 'Rembourser A1'),
        ('refund_a2', 'Rembourser A2'),
        ('split', 'Partager 50/50'),
    ]
    
    resolution = serializers.ChoiceField(choices=RESOLUTION_CHOICES)
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)