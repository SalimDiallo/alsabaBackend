"""
Serializers pour les modèles Wallet
Transforme les modèles Django en JSON pour l'API
"""
from rest_framework import serializers
from decimal import Decimal
from typing import Dict, Any, Optional
import uuid

from .models import Wallet, Transaction, Currency
from .Utils.currency_utils import format_amount


# ============================================================================
# SERIALIZERS DE BASE
# ============================================================================

class CurrencySerializer(serializers.ModelSerializer):
    """Serializer pour la devise"""
    
    class Meta:
        model = Currency
        fields = ['code', 'name', 'symbol', 'decimal_places', 'is_active']
        read_only_fields = fields


class WalletSerializer(serializers.ModelSerializer):
    """Serializer pour un wallet"""
    
    # Champs calculés
    currency_info = CurrencySerializer(source='currency', read_only=True)
    formatted_balance = serializers.SerializerMethodField()
    formatted_available_balance = serializers.SerializerMethodField()
    user_info = serializers.SerializerMethodField()
    
    class Meta:
        model = Wallet
        fields = [
            'id',
            'currency_info',
            'balance',
            'formatted_balance',
            'available_balance',
            'formatted_available_balance',
            'is_active',
            'created_at',
            'updated_at',
            'last_activity',
            'user_info',
        ]
        read_only_fields = fields
    
    def get_formatted_balance(self, obj: Wallet) -> str:
        """Retourne le solde formaté avec le symbole monétaire"""
        return format_amount(obj.balance, obj.currency.code)
    
    def get_formatted_available_balance(self, obj: Wallet) -> str:
        """Retourne le solde disponible formaté"""
        return format_amount(obj.available_balance, obj.currency.code)
    
    def get_user_info(self, obj: Wallet) -> Dict[str, Any]:
        """Retourne des infos basiques sur l'utilisateur"""
        return {
            'id': str(obj.user.id),
            'phone': obj.user.full_phone_number[-4:],  # Derniers 4 chiffres
            'kyc_status': obj.user.kyc_status,
            'kyc_verified': obj.user.kyc_status == 'verified',
        }


class TransactionSerializer(serializers.ModelSerializer):
    """Serializer pour une transaction"""
    
    # Champs calculés
    formatted_amount = serializers.SerializerMethodField()
    formatted_fee = serializers.SerializerMethodField()
    formatted_net_amount = serializers.SerializerMethodField()
    wallet_info = serializers.SerializerMethodField()
    transaction_type_display = serializers.CharField(
        source='get_transaction_type_display',
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    payment_method_display = serializers.CharField(
        source='get_payment_method_display',
        read_only=True
    )
    
    class Meta:
        model = Transaction
        fields = [
            'id',
            'transaction_type',
            'transaction_type_display',
            'status',
            'status_display',
            'amount',
            'formatted_amount',
            'fee',
            'formatted_fee',
            'net_amount',
            'formatted_net_amount',
            'reference',
            'external_reference',
            'description',
            'payment_method',
            'payment_method_display',
            'metadata',
            'created_at',
            'completed_at',
            'wallet_info',
        ]
        read_only_fields = fields
    
    def get_formatted_amount(self, obj) -> str:
        """Formatte le montant avec la devise"""
        # Gérer à la fois les instances de modèle et les dictionnaires
        if isinstance(obj, Transaction):  # Instance de modèle
            amount = obj.amount
            currency_code = obj.wallet.currency.code
        elif isinstance(obj, dict):  # Données sérialisées
            amount = obj.get('amount')
            # Essayer d'obtenir le code de devise du contexte d'abord
            currency_code = self.context.get('currency_code')
            if not currency_code:
                # Si pas dans le contexte, essayer d'extraire des données
                wallet_info = obj.get('wallet_info', {})
                if isinstance(wallet_info, dict):
                    currency_code = wallet_info.get('currency')
                elif hasattr(wallet_info, 'get'):
                    currency_code = wallet_info.get('currency')
        else:
            # Fallback : utiliser la devise de la requête ou EUR par défaut
            amount = getattr(obj, 'amount', 0)
            currency_code = self.context.get('currency_code', 'EUR')
        
        if amount is not None:
            return format_amount(amount, currency_code or 'EUR')
        return format_amount(0, 'EUR')
    
    def get_formatted_fee(self, obj) -> str:
        """Formatte les frais"""
        if isinstance(obj, Transaction):
            fee = obj.fee
            currency_code = obj.wallet.currency.code
        elif isinstance(obj, dict):
            fee = obj.get('fee', 0)
            currency_code = self.context.get('currency_code', 'EUR')
        else:
            fee = getattr(obj, 'fee', 0)
            currency_code = self.context.get('currency_code', 'EUR')
        
        return format_amount(fee, currency_code)
    
    def get_formatted_net_amount(self, obj) -> str:
        """Formatte le montant net"""
        if isinstance(obj, Transaction):
            net_amount = obj.net_amount
            currency_code = obj.wallet.currency.code
        elif isinstance(obj, dict):
            net_amount = obj.get('net_amount', 0)
            currency_code = self.context.get('currency_code', 'EUR')
        else:
            net_amount = getattr(obj, 'net_amount', 0)
            currency_code = self.context.get('currency_code', 'EUR')
        
        return format_amount(net_amount, currency_code)
    
    def get_wallet_info(self, obj) -> Dict[str, Any]:
        """Retourne des infos basiques sur le wallet"""
        if isinstance(obj, Transaction):
            return {
                'id': str(obj.wallet.id),
                'currency': obj.wallet.currency.code,
                'balance': float(obj.wallet.balance),
            }
        elif isinstance(obj, dict):
            # Si obj est déjà un dict, retourner les infos wallet si présentes
            wallet_info = obj.get('wallet_info')
            if wallet_info:
                return wallet_info
            # Sinon construire à partir des champs disponibles
            wallet_id = obj.get('wallet')
            currency = self.context.get('currency_code', 'EUR')
            balance = obj.get('wallet_balance', 0)
            
            if isinstance(wallet_id, Wallet):
                return {
                    'id': str(wallet_id.id),
                    'currency': wallet_id.currency.code,
                    'balance': float(wallet_id.balance),
                }
            else:
                return {
                    'id': str(wallet_id) if wallet_id else 'unknown',
                    'currency': currency,
                    'balance': float(balance),
                }
        else:
            return {
                'id': 'unknown',
                'currency': 'EUR',
                'balance': 0.0,
            }
# ============================================================================
# SERIALIZERS POUR LES REQUÊTES
# ============================================================================

class DepositRequestSerializer(serializers.Serializer):
    """
    Validation des données pour une demande de dépôt
    """
    
    amount = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        min_value=Decimal('0.01'),
        required=True,
        help_text="Montant à déposer"
    )
    
    payment_method = serializers.ChoiceField(
        choices=Transaction.PAYMENT_METHODS,
        required=True,
        help_text="Méthode de paiement"
    )
    
    description = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        help_text="Description optionnelle"
    )
    
    card_token = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        help_text="Token de carte (requis pour CARD)"
    )
    
    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validation globale"""
        payment_method = data.get('payment_method')
        card_token = data.get('card_token')
        
        # Vérifier le token de carte pour les paiements par carte
        if payment_method == 'CARD' and not card_token:
            raise serializers.ValidationError({
                'card_token': 'Token de carte requis pour les paiements par carte'
            })
        
        # Pour Orange Money, vérifier qu'on a un numéro de téléphone
        # (sera fait dans la vue avec l'utilisateur connecté)
        
        return data
    
    def validate_amount(self, value: Decimal) -> Decimal:
        """Validation du montant"""
        if value <= 0:
            raise serializers.ValidationError("Le montant doit être positif")
        
        # Vérifier les limites
        if value > Decimal('1000000'):  # 1 million max
            raise serializers.ValidationError("Montant maximum dépassé")
        
        return value


class WithdrawalRequestSerializer(serializers.Serializer):
    """
    Validation des données pour une demande de retrait
    """
    
    amount = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        min_value=Decimal('0.01'),
        required=True,
        help_text="Montant à retirer"
    )
    
    payment_method = serializers.ChoiceField(
        choices=Transaction.PAYMENT_METHODS,
        required=True,
        help_text="Méthode de retrait"
    )
    
    description = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        help_text="Description optionnelle"
    )
    
    bank_account_id = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        help_text="ID du compte bancaire (pour CARD)"
    )
    
    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validation globale"""
        payment_method = data.get('payment_method')
        bank_account_id = data.get('bank_account_id')
        
        # Pour les retraits par carte, vérifier les infos bancaires
        if payment_method == 'CARD' and not bank_account_id:
            raise serializers.ValidationError({
                'bank_account_id': 'Compte bancaire requis pour les retraits par carte'
            })
        
        return data
    
    def validate_amount(self, value: Decimal) -> Decimal:
        """Validation du montant"""
        if value <= 0:
            raise serializers.ValidationError("Le montant doit être positif")
        
        # Vérifier les limites
        if value > Decimal('50000'):  # 50,000 max pour les retraits
            raise serializers.ValidationError("Montant maximum de retrait dépassé")
        
        return value


class PaymentProviderSerializer(serializers.Serializer):
    """
    Serializer pour les informations d'un provider de paiement
    """
    
    name = serializers.CharField(max_length=50)
    display_name = serializers.CharField(max_length=100)
    supported_currencies = serializers.ListField(
        child=serializers.CharField(max_length=3)
    )
    min_amount = serializers.DictField(
        child=serializers.FloatField()
    )
    max_amount = serializers.DictField(
        child=serializers.FloatField()
    )
    deposit_fee_rate = serializers.DictField(
        child=serializers.FloatField()
    )
    withdrawal_fee_rate = serializers.DictField(
        child=serializers.FloatField()
    )


# ============================================================================
# SERIALIZERS POUR LES RÉPONSES
# ============================================================================

class WalletSummarySerializer(serializers.Serializer):
    """
    Serializer pour le résumé d'un wallet
    CORRIGÉ : Accepte maintenant un dict
    """
    wallet_id = serializers.UUIDField()
    currency = serializers.CharField(max_length=3)
    balance = serializers.FloatField()
    available_balance = serializers.FloatField()
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    last_activity = serializers.DateTimeField(allow_null=True)
    
    statistics = serializers.DictField()
    recent_transactions = serializers.ListField()
    user_info = serializers.DictField()
    
    # SUPPRIMER ces champs calculés car ils n'existent pas dans le dict
    # formatted_balance = serializers.CharField()
    # formatted_available_balance = serializers.CharField()


class TransactionHistoryResponseSerializer(serializers.Serializer):
    """
    Serializer pour la réponse de l'historique des transactions
    """
    
    transactions = TransactionSerializer(many=True)
    pagination = serializers.DictField()
    summary = serializers.DictField(required=False)


class DepositResponseSerializer(serializers.Serializer):
    """
    Serializer pour la réponse d'un dépôt
    """
    
    success = serializers.BooleanField()
    message = serializers.CharField()
    transaction = TransactionSerializer()
    new_balance = serializers.FloatField()
    provider_response = serializers.DictField(required=False)


class WithdrawalResponseSerializer(serializers.Serializer):
    """
    Serializer pour la réponse d'un retrait
    """
    
    success = serializers.BooleanField()
    message = serializers.CharField()
    transaction = TransactionSerializer()
    new_balance = serializers.FloatField()
    provider_response = serializers.DictField(required=False)


class PaymentInitiationResponseSerializer(serializers.Serializer):
    """
    Serializer pour la réponse d'initiation de paiement
    """
    
    success = serializers.BooleanField()
    message = serializers.CharField()
    transaction_id = serializers.UUIDField()
    provider_response = serializers.DictField()
    next_steps = serializers.DictField()


class ValidationResponseSerializer(serializers.Serializer):
    """
    Serializer pour la réponse de validation
    """
    
    valid = serializers.BooleanField()
    errors = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )
    warnings = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )
    fee = serializers.FloatField(required=False)
    net_amount = serializers.FloatField(required=False)
    can_proceed = serializers.BooleanField()
    next_step = serializers.CharField(required=False, allow_blank=True)
    available = serializers.FloatField(required=False)
    required = serializers.FloatField(required=False)


# ============================================================================
# SERIALIZERS POUR LES ERREURS
# ============================================================================

class ErrorResponseSerializer(serializers.Serializer):
    """
    Serializer standard pour les erreurs
    """
    
    success = serializers.BooleanField(default=False)
    error = serializers.CharField()
    code = serializers.CharField()
    details = serializers.DictField(required=False)
    next_step = serializers.CharField(required=False, allow_blank=True)


class WalletErrorResponseSerializer(ErrorResponseSerializer):
    """
    Serializer pour les erreurs spécifiques aux wallets
    """
    
    wallet_id = serializers.UUIDField(required=False)
    user_id = serializers.UUIDField(required=False)
    available_balance = serializers.FloatField(required=False)
    required_amount = serializers.FloatField(required=False)


# ============================================================================
# SERIALIZERS POUR LES WEBHOOKS
# ============================================================================

class WebhookPayloadSerializer(serializers.Serializer):
    """
    Serializer pour les payloads de webhook des providers
    """
    
    event_type = serializers.CharField()
    transaction_id = serializers.CharField()
    status = serializers.CharField()
    amount = serializers.FloatField(required=False)
    currency = serializers.CharField(max_length=3, required=False)
    metadata = serializers.DictField(required=False)
    signature = serializers.CharField(required=False)
    timestamp = serializers.DateTimeField(required=False)


class WebhookResponseSerializer(serializers.Serializer):
    """
    Serializer pour les réponses aux webhooks
    """
    
    received = serializers.BooleanField()
    processed = serializers.BooleanField()
    transaction_id = serializers.UUIDField(required=False)
    message = serializers.CharField(required=False)