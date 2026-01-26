"""
Sérialiseurs pour les méthodes de paiement sauvegardées
"""
from rest_framework import serializers
from decimal import Decimal
from ..models import PaymentMethod


class PaymentMethodSerializer(serializers.ModelSerializer):
    """
    Sérialiseur pour afficher une méthode de paiement sauvegardée
    """
    method_type_display = serializers.CharField(source='get_method_type_display', read_only=True)
    
    class Meta:
        model = PaymentMethod
        fields = [
            'id',
            'method_type',
            'method_type_display',
            'label',
            'card_last_four',
            'card_brand',
            'card_expiry_month',
            'card_expiry_year',
            'account_number_last_four',
            'bank_name',
            'account_name',
            'bank_country',
            'orange_money_number',
            'is_default',
            'is_active',
            'created_at',
            'updated_at',
            'last_used_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'last_used_at']


class CreateCardPaymentMethodSerializer(serializers.Serializer):
    """
    Sérialiseur pour créer une méthode de paiement carte
    """
    label = serializers.CharField(
        max_length=100,
        help_text="Nom donné à cette carte (ex: 'Ma carte principale')"
    )
    card_number = serializers.CharField(
        max_length=19,
        help_text="Numéro de carte complet"
    )
    card_expiry_month = serializers.IntegerField(
        min_value=1,
        max_value=12,
        help_text="Mois d'expiration (1-12)"
    )
    card_expiry_year = serializers.IntegerField(
        min_value=2024,
        max_value=2035,
        help_text="Année d'expiration"
    )
    card_cvv = serializers.CharField(
        max_length=4,
        help_text="CVV de la carte (requis pour la sauvegarde mais ne sera pas stocké)"
    )
    is_default = serializers.BooleanField(
        default=False,
        help_text="Définir comme méthode par défaut pour les dépôts par carte"
    )
    
    def validate_card_number(self, value):
        """Valide le numéro de carte"""
        card_number = value.replace(' ', '').replace('-', '')
        if not card_number.isdigit() or len(card_number) < 13 or len(card_number) > 19:
            raise serializers.ValidationError("Numéro de carte invalide")
        return card_number
    
    def validate(self, data):
        """Valide les données de la carte"""
        # Vérifier que la carte n'est pas expirée
        from datetime import date
        expiry_month = data.get('card_expiry_month')
        expiry_year = data.get('card_expiry_year')
        
        if expiry_month and expiry_year:
            expiry_date = date(expiry_year, expiry_month, 1)
            if expiry_date < date.today():
                raise serializers.ValidationError({
                    'card_expiry_month': "La carte est expirée"
                })
        
        return data


class CreateBankAccountPaymentMethodSerializer(serializers.Serializer):
    """
    Sérialiseur pour créer une méthode de paiement compte bancaire
    """
    label = serializers.CharField(
        max_length=100,
        help_text="Nom donné à ce compte (ex: 'Compte BNP')"
    )
    account_number = serializers.CharField(
        max_length=50,
        help_text="Numéro de compte bancaire"
    )
    bank_code = serializers.CharField(
        max_length=20,
        help_text="Code de la banque"
    )
    bank_name = serializers.CharField(
        max_length=200,
        required=False,
        help_text="Nom de la banque (optionnel)"
    )
    account_name = serializers.CharField(
        max_length=200,
        help_text="Nom du titulaire du compte"
    )
    bank_country = serializers.CharField(
        max_length=2,
        required=False,
        help_text="Code pays de la banque (ex: FR, SN, CI)"
    )
    is_default = serializers.BooleanField(
        default=False,
        help_text="Définir comme méthode par défaut pour les retraits vers compte bancaire"
    )
    
    def validate_account_number(self, value):
        """Valide le numéro de compte"""
        account_number = value.replace(' ', '').replace('-', '')
        if len(account_number) < 5:
            raise serializers.ValidationError("Numéro de compte invalide")
        return account_number


class CreateOrangeMoneyPaymentMethodSerializer(serializers.Serializer):
    """
    Sérialiseur pour créer une méthode de paiement Orange Money
    """
    label = serializers.CharField(
        max_length=100,
        help_text="Nom donné à ce numéro (ex: 'Mon Orange Money')"
    )
    orange_money_number = serializers.CharField(
        max_length=20,
        help_text="Numéro Orange Money"
    )
    is_default = serializers.BooleanField(
        default=False,
        help_text="Définir comme méthode par défaut pour Orange Money"
    )
    
    def validate_orange_money_number(self, value):
        """Valide le numéro Orange Money"""
        phone = value.replace(' ', '').replace('+', '')
        if not phone.isdigit() or len(phone) < 8:
            raise serializers.ValidationError("Format de numéro Orange Money invalide")
        return phone


class UpdatePaymentMethodSerializer(serializers.Serializer):
    """
    Sérialiseur pour mettre à jour une méthode de paiement
    """
    label = serializers.CharField(
        max_length=100,
        required=False,
        help_text="Nouveau nom"
    )
    is_default = serializers.BooleanField(
        required=False,
        help_text="Définir comme méthode par défaut"
    )
    is_active = serializers.BooleanField(
        required=False,
        help_text="Activer/désactiver la méthode"
    )
