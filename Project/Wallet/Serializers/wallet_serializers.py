from rest_framework import serializers
from decimal import Decimal
from ..models import Wallet, Transaction
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes


class WalletSerializer(serializers.ModelSerializer):
    """
    Sérialiseur pour le portefeuille
    """
    balance = serializers.SerializerMethodField()
    locked_balance = serializers.SerializerMethodField()
    available_balance = serializers.SerializerMethodField()
    currency_display = serializers.SerializerMethodField()
    user_phone = serializers.CharField(source='user.full_phone_number', read_only=True)
    transactions_count = serializers.SerializerMethodField()
    recent_transactions = serializers.SerializerMethodField()
    currency_info = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = [
            'id',
            'balance',
            'locked_balance',
            'available_balance',
            'currency',
            'currency_display',
            'user_phone',
            'is_active',
            'created_at',
            'updated_at',

            # Champs calculés
            'transactions_count',
            'recent_transactions',
            'currency_info',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def _locked_cents(self, obj):
        """Somme des fonds actuellement bloqués en escrow pour cet utilisateur."""
        from django.db.models import Sum
        from Offer.models import EscrowLock
        return EscrowLock.objects.filter(
            user=obj.user, status='LOCKED'
        ).aggregate(s=Sum('amount_cents'))['s'] or 0

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_balance(self, obj):
        """Solde total (inclut les fonds bloqués en escrow)."""
        return float(obj.balance)

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_locked_balance(self, obj):
        """Fonds bloqués en escrow (offres en cours)."""
        return float(Decimal(self._locked_cents(obj)) / 100)

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_available_balance(self, obj):
        """Solde réellement disponible = total - bloqué. C'est ce que l'utilisateur peut engager."""
        return float(Decimal(obj.balance_cents - self._locked_cents(obj)) / 100)

    @extend_schema_field(OpenApiTypes.STR)
    def get_currency_display(self, obj):
        """Retourne le nom complet de la devise"""
        return obj.currency_name

    @extend_schema_field(OpenApiTypes.INT)
    def get_transactions_count(self, obj):
        return obj.transactions.count()

    @extend_schema_field(serializers.ListField(child=serializers.JSONField()))
    def get_recent_transactions(self, obj):
        from ..Serializers.wallet_serializers import TransactionSerializer
        return TransactionSerializer(
            obj.transactions.order_by('-created_at')[:5],
            many=True
        ).data

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_currency_info(self, obj):
        from ..Services.wallet_service import WalletService
        return {
            'code': obj.currency,
            'symbol': WalletService._get_currency_symbol(obj.currency),
            'name': WalletService._get_currency_name(obj.currency)
        }


class TransactionSerializer(serializers.ModelSerializer):
    """
    Sérialiseur pour les transactions
    """
    amount = serializers.SerializerMethodField()
    fee = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    currency_display = serializers.SerializerMethodField()
    payment_method_saved_info = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id',
            'transaction_type',
            'transaction_type_display',
            'payment_method',
            'payment_method_display',
            'payment_method_saved',
            'payment_method_saved_info',
            'amount',
            'fee',
            'currency',
            'currency_display',
            'status',
            'status_display',
            'flutterwave_reference',
            'created_at',
            'updated_at',
            'completed_at',
        ]
        read_only_fields = ['id', 'flutterwave_reference', 'created_at', 'updated_at', 'completed_at']

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_amount(self, obj):
        return float(obj.amount_euros)

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_fee(self, obj):
        return float(obj.fee_euros)

    @extend_schema_field(OpenApiTypes.STR)
    def get_currency_display(self, obj):
        """Retourne le nom complet de la devise"""
        # On utilise le modèle Wallet pour centraliser les noms de devises
        return obj.wallet.currency_name
    
    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_payment_method_saved_info(self, obj):
        """Retourne les informations de la méthode de paiement sauvegardée si disponible"""
        if obj.payment_method_saved:
            # Note: Pour une performance optimale, assurez-vous que la vue utilise .select_related('payment_method_saved')
            from ..Serializers.payment_method_serializers import PaymentMethodSerializer
            return PaymentMethodSerializer(obj.payment_method_saved, context=self.context).data
        return None


class DepositSerializer(serializers.Serializer):
    """
    Sérialiseur pour l'initiation d'un dépôt
    Accepte soit un payment_method_id (méthode sauvegardée) soit les détails complets
    """
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.01'),
        help_text="Montant du dépôt dans la devise du portefeuille"
    )
    payment_method = serializers.ChoiceField(
        choices=[('card', 'Carte bancaire'), ('orange_money', 'Orange Money')],
        help_text="Méthode de paiement"
    )
    redirect_url = serializers.URLField(
        required=False,
        help_text="URL de redirection après paiement (optionnel)"
    )
    
    # Option 1: Utiliser une méthode de paiement sauvegardée
    payment_method_id = serializers.UUIDField(
        required=False,
        help_text="ID d'une méthode de paiement sauvegardée (alternative aux détails ci-dessous)"
    )
    
    # Option 2: Détails complets (si pas de payment_method_id)
    # Champs pour paiement par carte
    card_number = serializers.CharField(
        required=False,
        max_length=19,
        help_text="Numéro de carte (requis si pas de payment_method_id)"
    )
    card_expiry_month = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=12,
        help_text="Mois d'expiration (requis si pas de payment_method_id)"
    )
    card_expiry_year = serializers.IntegerField(
        required=False,
        min_value=2024,
        max_value=2035,
        help_text="Année d'expiration (requis si pas de payment_method_id)"
    )
    card_cvv = serializers.CharField(
        required=False,
        max_length=4,
        help_text="CVV de la carte (toujours requis même avec payment_method_id)"
    )
    
    # Option 3: Token de carte (PCI-DSS)
    card_token = serializers.CharField(
        required=False,
        help_text="Token de carte généré par le frontend (alternative aux détails complets)"
    )
    
    # Option pour sauvegarder la méthode de paiement
    save_payment_method = serializers.BooleanField(
        default=False,
        help_text="Sauvegarder cette méthode de paiement pour usage futur"
    )
    payment_method_label = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Nom à donner à la méthode sauvegardée (si save_payment_method=True)"
    )

    def validate_amount(self, value):
        # Validation supplémentaire selon la devise
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            wallet = request.user.wallet
            # Pour les devises africaines, ajuster les limites si nécessaire
            if wallet.currency in ['XAF', 'XOF']:
                # Franc CFA - minimum 500 FCFA
                if value < 5:
                    raise serializers.ValidationError("Le montant minimum est de 500 FCFA")
            elif wallet.currency == 'NGN':
                # Naira - minimum 100 NGN
                if value < 1:
                    raise serializers.ValidationError("Le montant minimum est de 100 NGN")
        return value

    def validate(self, data):
        payment_method = data.get('payment_method')
        payment_method_id = data.get('payment_method_id')
        card_token = data.get('card_token')
        
        # Si payment_method_id est fourni, on n'a pas besoin des détails
        if payment_method_id:
            # CVV toujours requis pour les cartes même avec payment_method_id
            if payment_method == 'card':
                 # Note: Avec payment_method_id, si on a un token backend, le CVV peut être optionnel selon config Flutterwave
                 # Pour l'instant on garde la contrainte existante ou on l'assouplit si besoin
                 if not data.get('card_cvv'):
                    raise serializers.ValidationError({
                        'card_cvv': "CVV requis même avec une méthode sauvegardée"
                    })
            return data
        
        # Si un token frontend est fourni (PCI-DSS compliant flow)
        if card_token:
            return data
        
        # Sinon, on doit avoir tous les détails
        if payment_method == 'card':
            required_fields = ['card_number', 'card_expiry_month', 'card_expiry_year', 'card_cvv']
            for field in required_fields:
                if not data.get(field):
                    raise serializers.ValidationError({
                        field: f"Ce champ est requis pour les paiements par carte (ou utilisez payment_method_id / card_token)"
                    })

            # Validation basique du numéro de carte
            card_number = data.get('card_number', '').replace(' ', '')
            if not card_number.isdigit() or len(card_number) < 13 or len(card_number) > 19:
                raise serializers.ValidationError({
                    'card_number': "Numéro de carte invalide"
                })
            
            # Si on veut sauvegarder, il faut un label
            if data.get('save_payment_method') and not data.get('payment_method_label'):
                raise serializers.ValidationError({
                    'payment_method_label': "Un nom est requis pour sauvegarder la méthode de paiement"
                })

        # Pour Orange Money, pas de validation supplémentaire car on utilise le numéro de l'utilisateur

        return data


class WithdrawalSerializer(serializers.Serializer):
    """
    Sérialiseur pour l'initiation d'un retrait
    Accepte soit un payment_method_id (méthode sauvegardée) soit les détails complets
    """
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.01'),
        help_text="Montant du retrait dans la devise du portefeuille"
    )
    payment_method = serializers.ChoiceField(
        choices=[('card', 'Compte bancaire'), ('orange_money', 'Orange Money')],
        help_text="Méthode de retrait"
    )
    
    # Option 1: Utiliser une méthode de paiement sauvegardée
    payment_method_id = serializers.UUIDField(
        required=False,
        help_text="ID d'une méthode de paiement sauvegardée (alternative aux détails ci-dessous)"
    )
    
    # Option 2: Détails complets (si pas de payment_method_id)
    # Champs pour retrait vers compte bancaire
    account_number = serializers.CharField(
        required=False,
        max_length=50,
        help_text="Numéro de compte bancaire (requis si pas de payment_method_id)"
    )
    bank_code = serializers.CharField(
        required=False,
        max_length=20,
        help_text="Code de la banque (requis si pas de payment_method_id)"
    )
    account_name = serializers.CharField(
        required=False,
        max_length=200,
        help_text="Nom du titulaire du compte (requis si pas de payment_method_id)"
    )
    bank_country = serializers.CharField(
        required=False,
        max_length=2,
        help_text="Code pays de la banque (ex: FR, SN, CI) - optionnel"
    )
    bank_name = serializers.CharField(
        required=False,
        max_length=200,
        help_text="Nom de la banque (optionnel)"
    )

    # Champs pour Orange Money
    orange_money_number = serializers.CharField(
        required=False,
        max_length=20,
        help_text="Numéro Orange Money (requis si pas de payment_method_id)"
    )
    
    # Option pour sauvegarder la méthode de paiement
    save_payment_method = serializers.BooleanField(
        default=False,
        help_text="Sauvegarder cette méthode de paiement pour usage futur"
    )
    payment_method_label = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Nom à donner à la méthode sauvegardée (si save_payment_method=True)"
    )

    def validate_amount(self, value):
        # Validation selon la devise du wallet
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            wallet = request.user.wallet
            # Vérifications spécifiques selon la devise
            if wallet.currency in ['XAF', 'XOF']:
                if value < 10:  # Minimum 1,000 FCFA
                    raise serializers.ValidationError("Le montant minimum est de 1,000 FCFA")
            elif wallet.currency == 'NGN':
                if value < 5:  # Minimum 500 NGN
                    raise serializers.ValidationError("Le montant minimum est de 500 NGN")
        return value

    def validate(self, data):
        payment_method = data.get('payment_method')
        payment_method_id = data.get('payment_method_id')
        
        # Si payment_method_id est fourni, on n'a pas besoin des détails
        if payment_method_id:
            return data
        
        # Sinon, on doit avoir tous les détails
        if payment_method == 'card':
            # Retrait vers compte bancaire
            required_fields = ['account_number', 'bank_code', 'account_name']
            for field in required_fields:
                if not data.get(field):
                    raise serializers.ValidationError({
                        field: f"Ce champ est requis pour les retraits vers compte bancaire (ou utilisez payment_method_id)"
                    })

            # Validation basique du numéro de compte
            account_number = data.get('account_number', '').replace(' ', '')
            if not account_number or len(account_number) < 5:
                raise serializers.ValidationError({
                    'account_number': "Numéro de compte bancaire invalide"
                })
            
            # Si on veut sauvegarder, il faut un label
            if data.get('save_payment_method') and not data.get('payment_method_label'):
                raise serializers.ValidationError({
                    'payment_method_label': "Un nom est requis pour sauvegarder la méthode de paiement"
                })

        elif payment_method == 'orange_money':
            if not data.get('orange_money_number'):
                raise serializers.ValidationError({
                    'orange_money_number': "Numéro Orange Money requis (ou utilisez payment_method_id)"
                })

            # Validation basique du numéro
            phone = data.get('orange_money_number', '').replace(' ', '').replace('+', '')
            if not phone.isdigit() or len(phone) < 8:
                raise serializers.ValidationError({
                    'orange_money_number': "Format de numéro Orange Money invalide"
                })
            
            # Si on veut sauvegarder, il faut un label
            if data.get('save_payment_method') and not data.get('payment_method_label'):
                raise serializers.ValidationError({
                    'payment_method_label': "Un nom est requis pour sauvegarder la méthode de paiement"
                })

        return data


class TransactionListSerializer(serializers.Serializer):
    """
    Sérialiseur pour les paramètres de liste de transactions
    """
    transaction_type = serializers.ChoiceField(
        choices=[('deposit', 'Dépôt'), ('withdrawal', 'Retrait')],
        required=False
    )
    status = serializers.ChoiceField(
        choices=[
            ('pending', 'En attente'),
            ('processing', 'En cours'),
            ('completed', 'Terminée'),
            ('failed', 'Échouée'),
            ('cancelled', 'Annulée')
        ],
        required=False
    )
    payment_method = serializers.ChoiceField(
        choices=[('card', 'Carte bancaire'), ('orange_money', 'Orange Money')],
        required=False
    )
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)


class TransactionConfirmSerializer(serializers.Serializer):
    """
    Sérialiseur pour la confirmation d'une transaction
    """
    transaction_id = serializers.UUIDField(required=False)
    confirmation_code = serializers.CharField(max_length=10, required=False, help_text="Code de confirmation si requis")
    notes = serializers.CharField(max_length=500, required=False, help_text="Notes supplémentaires")


class TransactionCancelSerializer(serializers.Serializer):
    """
    Sérialiseur pour l'annulation d'une transaction
    """
    transaction_id = serializers.UUIDField(required=False)
    reason = serializers.CharField(max_length=500, required=True, help_text="Raison de l'annulation")
    notes = serializers.CharField(max_length=500, required=False, help_text="Notes supplémentaires")


class TransactionStatusUpdateSerializer(serializers.Serializer):
    """
    Sérialiseur pour la mise à jour du statut d'une transaction (admin)
    """
    status = serializers.ChoiceField(
        choices=[
            ('pending', 'En attente'),
            ('processing', 'En cours'),
            ('completed', 'Terminée'),
            ('failed', 'Échouée'),
            ('cancelled', 'Annulée')
        ],
        required=True
    )
    error_message = serializers.CharField(max_length=500, required=False)
    error_code = serializers.CharField(max_length=100, required=False)
    notes = serializers.CharField(max_length=500, required=False)


class EstimateFeesSerializer(serializers.Serializer):
    """
    Sérialiseur pour l'estimation des frais
    """
    transaction_type = serializers.ChoiceField(choices=[('deposit', 'Dépôt'), ('withdrawal', 'Retrait')])
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    payment_method = serializers.ChoiceField(choices=[('card', 'Carte bancaire'), ('orange_money', 'Orange Money')])
    currency = serializers.CharField(required=False, max_length=10)
