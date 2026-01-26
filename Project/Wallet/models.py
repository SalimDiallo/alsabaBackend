from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid
import structlog
import pycountry
import phonenumbers
from decimal import Decimal
from phonenumbers import PhoneNumberFormat

logger = structlog.get_logger(__name__)


class Wallet(models.Model):
    """
    Portefeuille électronique associé à chaque utilisateur
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wallet'
    )

    # Devise déterminée automatiquement par le pays du numéro de téléphone
    currency = models.CharField(
        max_length=3,
        help_text="Devise du portefeuille (déterminée par le pays du numéro de téléphone)"
    )

    # Solde en centimes pour éviter les problèmes de précision
    balance_cents = models.BigIntegerField(default=0, db_index=True)

    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "wallets"
        verbose_name = "Portefeuille"
        verbose_name_plural = "Portefeuilles"
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['currency']),
            models.Index(fields=['balance_cents']),
        ]

    def __str__(self):
        return f"Wallet de {self.user.full_phone_number} ({self.currency})"

    @property
    def balance(self):
        """Retourne le solde en euros (ou devise équivalente)"""
        return self.balance_cents / 100

    @balance.setter
    def balance(self, value):
        """Définit le solde en euros (ou devise équivalente)"""
        self.balance_cents = int(value * 100)

    def add_balance(self, amount):
        """Ajoute un montant au solde de manière atomique"""
        from django.db.models import F
        amount_cents = int(Decimal(str(amount)) * 100)
        self.balance_cents = F('balance_cents') + amount_cents
        self.save(update_fields=['balance_cents'])
        self.refresh_from_db()
        logger.info("wallet_balance_added_atomic", user_id=str(self.user.id), amount=amount, new_balance=self.balance, currency=self.currency)

    def subtract_balance(self, amount):
        """Soustrait un montant du solde de manière atomique"""
        from django.db.models import F
        amount_cents = int(Decimal(str(amount)) * 100)
        
        # Note: La vérification du solde ici est indicative car F() n'est évalué qu'en DB.
        # En production, on utilise select_for_update() dans le service pour une vérification rigoureuse.
        self.balance_cents = F('balance_cents') - amount_cents
        self.save(update_fields=['balance_cents'])
        self.refresh_from_db()
        logger.info("wallet_balance_subtracted_atomic", user_id=str(self.user.id), amount=amount, new_balance=self.balance, currency=self.currency)

    @staticmethod
    def get_currency_from_phone_number(phone_number):
        """
        Détermine la devise basée sur le pays du numéro de téléphone

        Args:
            phone_number: Numéro de téléphone au format E.164

        Returns:
            str: Code devise (EUR, XAF, etc.)
        """
        try:
            # Parse le numéro pour obtenir le code pays
            parsed = phonenumbers.parse(phone_number, None)
            
            # Utiliser le code de région (ex: 'FR', 'CM') directement
            region_code = phonenumbers.region_code_for_number(parsed)

            if region_code:
                # Mapping des pays vers leurs devises
                currency_mapping = {
                    # Zone Euro
                    'FR': 'EUR', 'DE': 'EUR', 'IT': 'EUR', 'ES': 'EUR', 'NL': 'EUR',
                    'BE': 'EUR', 'AT': 'EUR', 'PT': 'EUR', 'FI': 'EUR', 'IE': 'EUR',
                    'LU': 'EUR', 'MT': 'EUR', 'CY': 'EUR', 'SK': 'EUR', 'SI': 'EUR',
                    'EE': 'EUR', 'LV': 'EUR', 'LT': 'EUR', 'GR': 'EUR',

                    # Afrique Francophone (XAF - Franc CFA)
                    'CM': 'XAF', 'GA': 'XAF', 'CF': 'XAF', 'TD': 'XAF', 'GQ': 'XAF', 'CG': 'XAF',

                    # Afrique Anglophone
                    'NG': 'NGN', 'GH': 'GHS', 'KE': 'KES', 'ZA': 'ZAR', 'TZ': 'TZS',
                    'UG': 'UGX', 'RW': 'RWF', 'BI': 'BIF', 'ZM': 'ZMW', 'ZW': 'ZWD',

                    # Côte d'Ivoire (XOF - Franc CFA BCEAO)
                    'CI': 'XOF', 'SN': 'XOF', 'ML': 'XOF', 'BJ': 'XOF', 'BF': 'XOF',
                    'TG': 'XOF', 'NE': 'XOF', 'GW': 'XOF',
                }

                return currency_mapping.get(region_code, 'EUR')  # EUR par défaut

            return 'EUR'  # Devise par défaut

        except (phonenumbers.NumberParseException, AttributeError) as e:
            logger.warning("currency_detection_failed", phone_number=phone_number, error=str(e))
            return 'EUR'  # Devise par défaut

    def save(self, *args, **kwargs):
        # Détermine automatiquement la devise si elle n'est pas définie
        if not self.currency and self.user:
            self.currency = self.get_currency_from_phone_number(self.user.full_phone_number)
        super().save(*args, **kwargs)


class PaymentMethod(models.Model):
    """
    Méthodes de paiement sauvegardées par l'utilisateur
    Permet de ne pas ressaisir les informations à chaque transaction
    """
    PAYMENT_METHOD_TYPES = (
        ('card', 'Carte bancaire'),
        ('bank_account', 'Compte bancaire'),
        ('orange_money', 'Orange Money'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payment_methods'
    )
    
    # Type de méthode de paiement
    method_type = models.CharField(max_length=20, choices=PAYMENT_METHOD_TYPES)
    
    # Nom/label donné par l'utilisateur (ex: "Ma carte principale", "Compte BNP")
    label = models.CharField(max_length=100, help_text="Nom donné par l'utilisateur")
    
    # Informations pour carte bancaire (stockées de manière sécurisée)
    card_last_four = models.CharField(max_length=4, blank=True, null=True, help_text="4 derniers chiffres")
    card_brand = models.CharField(max_length=50, blank=True, null=True, help_text="Visa, Mastercard, etc.")
    card_expiry_month = models.IntegerField(blank=True, null=True, help_text="Mois d'expiration (1-12)")
    card_expiry_year = models.IntegerField(blank=True, null=True, help_text="Année d'expiration")
    # Note: On ne stocke JAMAIS le numéro complet ni le CVV pour des raisons de sécurité
    
    # Informations pour compte bancaire
    account_number = models.CharField(max_length=50, blank=True, null=True, help_text="Numéro de compte (masqué)")
    account_number_last_four = models.CharField(max_length=4, blank=True, null=True, help_text="4 derniers chiffres")
    bank_code = models.CharField(max_length=20, blank=True, null=True, help_text="Code de la banque")
    bank_name = models.CharField(max_length=200, blank=True, null=True, help_text="Nom de la banque")
    account_name = models.CharField(max_length=200, blank=True, null=True, help_text="Nom du titulaire")
    bank_country = models.CharField(max_length=2, blank=True, null=True, help_text="Code pays de la banque")
    
    # Informations pour Orange Money
    orange_money_number = models.CharField(max_length=20, blank=True, null=True, help_text="Numéro Orange Money")
    
    # Métadonnées
    is_default = models.BooleanField(default=False, help_text="Méthode par défaut pour ce type")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    
    # Référence Flutterwave (si applicable)
    flutterwave_payment_method_id = models.CharField(max_length=100, blank=True, null=True)
    flutterwave_recipient_id = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        db_table = "payment_methods"
        verbose_name = "Méthode de paiement"
        verbose_name_plural = "Méthodes de paiement"
        indexes = [
            models.Index(fields=['user', 'method_type', 'is_active']),
            models.Index(fields=['user', 'is_default']),
        ]

    def __str__(self):
        if self.method_type == 'card':
            return f"{self.label} - {self.card_brand or 'Carte'} ****{self.card_last_four}"
        elif self.method_type == 'bank_account':
            return f"{self.label} - {self.bank_name or 'Banque'} ****{self.account_number_last_four}"
        elif self.method_type == 'orange_money':
            return f"{self.label} - {self.orange_money_number}"
        return self.label

    def mark_as_used(self):
        """Marque la méthode comme utilisée"""
        self.last_used_at = timezone.now()
        self.save(update_fields=['last_used_at'])


class Transaction(models.Model):
    """
    Transaction financière (dépôt ou retrait)
    """

    TRANSACTION_TYPES = (
        ('deposit', 'Dépôt'),
        ('withdrawal', 'Retrait'),
    )

    PAYMENT_METHODS = (
        ('card', 'Carte bancaire'),
        ('orange_money', 'Orange Money'),
    )

    STATUS_CHOICES = (
        ('pending', 'En attente'),
        ('processing', 'En cours'),
        ('completed', 'Terminée'),
        ('failed', 'Échouée'),
        ('cancelled', 'Annulée'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    
    # Lien vers la méthode de paiement sauvegardée (optionnel)
    payment_method_saved = models.ForeignKey(
        PaymentMethod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions',
        help_text="Méthode de paiement sauvegardée utilisée"
    )

    # Type et méthode
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)

    # Devise de la transaction (hérite de celle du wallet)
    currency = models.CharField(max_length=3, help_text="Devise de la transaction")

    # Montants dans la devise locale (en centimes pour précision)
    amount_cents = models.BigIntegerField(help_text="Montant en centimes dans la devise locale")
    fee_cents = models.BigIntegerField(default=0, help_text="Frais en centimes dans la devise locale")

    # Taux de conversion si nécessaire (vers EUR pour les calculs)
    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Taux de conversion vers EUR (si applicable)"
    )

    # Statut et tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    flutterwave_reference = models.CharField(max_length=100, blank=True, null=True)
    flutterwave_transaction_id = models.CharField(max_length=100, blank=True, null=True)

    # Métadonnées utilisateur
    user_ip = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)

    # Informations de paiement spécifiques à la méthode
    card_last_four = models.CharField(max_length=4, blank=True, null=True)  # Pour carte
    orange_money_number = models.CharField(max_length=20, blank=True, null=True)  # Pour Orange Money

    # Messages d'erreur
    error_message = models.TextField(blank=True, null=True)
    error_code = models.CharField(max_length=50, blank=True, null=True)

    # Sécurité: Indique si le solde du wallet a déjà été impacté
    balance_adjusted = models.BooleanField(default=False, help_text="Vrai si le solde du wallet a été mis à jour")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "transactions"
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', 'status']),
            models.Index(fields=['transaction_type', 'status']),
            models.Index(fields=['currency']),
            models.Index(fields=['flutterwave_reference']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.transaction_type} de {self.amount_euros} {self.currency} - {self.get_status_display()}"

    @property
    def amount_euros(self):
        """Montant en devise locale (pour compatibilité)"""
        return self.amount_cents / 100

    @property
    def fee_euros(self):
        """Frais en devise locale"""
        return self.fee_cents / 100

    def save(self, *args, **kwargs):
        # Hérite de la devise du wallet
        if not self.currency and self.wallet:
            self.currency = self.wallet.currency

        # Timestamp de completion
        if self.status == 'completed' and not self.completed_at:
            self.completed_at = timezone.now()
        elif self.status != 'completed' and self.completed_at:
            self.completed_at = None

        super().save(*args, **kwargs)

    def mark_completed(self):
        """Marque la transaction comme terminée"""
        # Éviter de traiter deux fois la même transaction
        if self.status == 'completed':
            logger.warning(
                "transaction_already_completed",
                transaction_id=str(self.id),
                current_status=self.status
            )
            return
        
        self.status = 'completed'
        self.completed_at = timezone.now()
        
        # Met à jour le solde du wallet seulement s'il ne l'a pas déjà été
        if not self.balance_adjusted:
            from decimal import Decimal
            if self.transaction_type == 'deposit':
                self.wallet.add_balance(self.amount_euros)
                self.balance_adjusted = True
            elif self.transaction_type == 'withdrawal':
                # Débiter le montant + les frais
                total_deduct = (Decimal(self.amount_cents) + Decimal(self.fee_cents)) / 100
                self.wallet.subtract_balance(total_deduct)
                self.balance_adjusted = True

        self.save()

    def mark_failed(self, error_message=None, error_code=None):
        """Marque la transaction comme échouée"""
        self.status = 'failed'
        self.error_message = error_message
        self.error_code = error_code
        self.save()

        logger.warning(
            "transaction_failed",
            transaction_id=str(self.id),
            user_id=str(self.wallet.user.id),
            currency=self.currency,
            error_code=error_code,
            error_message=error_message
        )

    def mark_cancelled(self, reason=None, notes=None):
        """Marque la transaction comme annulée"""
        self.status = 'cancelled'
        if reason:
            self.error_message = reason
        if notes:
            # Stocker les notes dans error_message si pas de reason, ou dans un champ dédié si disponible
            if not reason:
                self.error_message = notes
        self.save()

        logger.info(
            "transaction_cancelled",
            transaction_id=str(self.id),
            user_id=str(self.wallet.user.id),
            currency=self.currency,
            reason=reason
        )
