from rest_framework import serializers
from django.utils import timezone
from decimal import Decimal
from ..models import Wallet, Transaction


class WalletSerializer(serializers.ModelSerializer):
    """
    Sérialiseur pour le portefeuille
    """
    balance = serializers.SerializerMethodField()
    currency_display = serializers.SerializerMethodField()
    user_phone = serializers.CharField(source='user.full_phone_number', read_only=True)

    class Meta:
        model = Wallet
        fields = [
            'id',
            'balance',
            'currency',
            'currency_display',
            'user_phone',
            'is_active',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_balance(self, obj):
        return float(obj.balance)

    def get_currency_display(self, obj):
        """Retourne le nom complet de la devise"""
        currency_names = {
            'EUR': 'Euro',
            'XAF': 'Franc CFA (CEMAC)',
            'XOF': 'Franc CFA (BCEAO)',
            'NGN': 'Naira Nigérian',
            'GHS': 'Cedi Ghanéen',
            'KES': 'Shilling Kényan',
            'ZAR': 'Rand Sud-Africain',
            'TZS': 'Shilling Tanzanien',
            'UGX': 'Shilling Ougandais',
            'RWF': 'Franc Rwandais',
            'BIF': 'Franc Burundais',
            'ZMW': 'Kwacha Zambien',
            'ZWD': 'Dollar Zimbabwéen',
        }
        return currency_names.get(obj.currency, obj.currency)


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

    def get_amount(self, obj):
        return float(obj.amount_euros)

    def get_fee(self, obj):
        return float(obj.fee_euros)

    def get_currency_display(self, obj):
        """Retourne le nom complet de la devise"""
        currency_names = {
            'EUR': 'Euro',
            'XAF': 'Franc CFA (CEMAC)',
            'XOF': 'Franc CFA (BCEAO)',
            'NGN': 'Naira Nigérian',
            'GHS': 'Cedi Ghanéen',
            'KES': 'Shilling Kényan',
            'ZAR': 'Rand Sud-Africain',
            'TZS': 'Shilling Tanzanien',
            'UGX': 'Shilling Ougandais',
            'RWF': 'Franc Rwandais',
            'BIF': 'Franc Burundais',
            'ZMW': 'Kwacha Zambien',
            'ZWD': 'Dollar Zimbabwéen',
        }
        return currency_names.get(obj.currency, obj.currency)
    
    def get_payment_method_saved_info(self, obj):
        """Retourne les informations de la méthode de paiement sauvegardée si disponible"""
        if obj.payment_method_saved:
            from ..Serializers.payment_method_serializers import PaymentMethodSerializer
            return PaymentMethodSerializer(obj.payment_method_saved).data
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
        
        # Si payment_method_id est fourni, on n'a pas besoin des détails
        if payment_method_id:
            # CVV toujours requis pour les cartes même avec payment_method_id
            if payment_method == 'card' and not data.get('card_cvv'):
                raise serializers.ValidationError({
                    'card_cvv': "CVV requis même avec une méthode sauvegardée"
                })
            return data
        
        # Sinon, on doit avoir tous les détails
        if payment_method == 'card':
            required_fields = ['card_number', 'card_expiry_month', 'card_expiry_year', 'card_cvv']
            for field in required_fields:
                if not data.get(field):
                    raise serializers.ValidationError({
                        field: f"Ce champ est requis pour les paiements par carte (ou utilisez payment_method_id)"
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
    transaction_id = serializers.UUIDField(required=True)
    confirmation_code = serializers.CharField(max_length=10, required=False, help_text="Code de confirmation si requis")
    notes = serializers.CharField(max_length=500, required=False, help_text="Notes supplémentaires")


class TransactionCancelSerializer(serializers.Serializer):
    """
    Sérialiseur pour l'annulation d'une transaction
    """
    transaction_id = serializers.UUIDField(required=True)
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