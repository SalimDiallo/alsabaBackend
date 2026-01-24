from rest_framework import serializers
from ..models import Wallet
from decimal import Decimal
class WalletSerializer(serializers.ModelSerializer):
    """
    Sérialiseur pour afficher le wallet.
    - Inclut le solde disponible calculé.
    - Tout en lecture seule pour sécurité.
    """
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    currency_name = serializers.CharField(source='currency.name', read_only=True)
    currency_symbol = serializers.CharField(source='currency.symbol', read_only=True)
    available_balance = serializers.DecimalField(max_digits=24, decimal_places=8, read_only=True)

    class Meta:
        model = Wallet
        fields = [
            'id', 'currency_code', 'currency_name', 'currency_symbol',
            'balance', 'available_balance', 'created_at', 'updated_at'
        ]
        read_only_fields = fields


class DepositSerializer(serializers.Serializer):
    """
    Sérialiseur pour les dépôts.
    - Valide montant min (ex: 1.00).
    - Méthode : orange_money ou card.
    """
    amount = serializers.DecimalField(
        max_digits=24,
        decimal_places=8,
        min_value=Decimal('1.00'),
        required=True
    )
    method = serializers.ChoiceField(
        choices=['orange_money', 'card'],
        required=True
    )
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)  # Optionnel pour placeholders

class WithdrawalSerializer(serializers.Serializer):
    """
    Validation pour les retraits.
    """
    amount = serializers.DecimalField(
        max_digits=24,
        decimal_places=8,
        min_value=Decimal('1.00'),
        required=True
    )
    method = serializers.ChoiceField(
        choices=['orange_money', 'card', 'bank_transfer'],
        required=True
    )
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)
    # Optionnel : on pourra ajouter iban, phone_number, etc. plus tard