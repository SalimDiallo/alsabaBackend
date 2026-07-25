from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid
import structlog
import phonenumbers
from decimal import Decimal
from fernet_fields import EncryptedCharField

logger = structlog.get_logger(__name__)


class Wallet(models.Model):
    """
    Electronic wallet associated with each user
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wallet'
    )

    # Currency determined automatically by phone number country
    currency = models.CharField(
        max_length=3,
        help_text="Wallet currency (determined by phone number country)"
    )

    CURRENCY_NAMES = {
        'EUR': 'Euro',
        'XAF': 'CFA Franc (CEMAC)',
        'XOF': 'CFA Franc (BCEAO)',
        'NGN': 'Nigerian Naira',
        'GHS': 'Ghanaian Cedi',
        'KES': 'Kenyan Shilling',
        'ZAR': 'South African Rand',
        'TZS': 'Tanzanian Shilling',
        'UGX': 'Ugandan Shilling',
        'RWF': 'Rwandan Franc',
        'BIF': 'Burundian Franc',
        'ZMW': 'Zambian Kwacha',
        'ZWD': 'Zimbabwean Dollar',
        'MAD': 'Moroccan Dirham',
        'DZD': 'Algerian Dinar',
        'TND': 'Tunisian Dinar',
        'EGP': 'Egyptian Pound',
        'USD': 'US Dollar',
        'GBP': 'British Pound',
    }

    # Balance in cents to avoid precision issues
    balance_cents = models.BigIntegerField(default=0, db_index=True)

    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    # Optimistic Locking
    version = models.IntegerField(default=0, help_text="Version for optimistic locking")

    class Meta:
        db_table = "wallets"
        verbose_name = "Wallet"
        verbose_name_plural = "Wallets"
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['currency']),
            models.Index(fields=['balance_cents']),
        ]
        constraints = [
            models.CheckConstraint(check=models.Q(balance_cents__gte=0), name='positive_balance_constraint')
        ]

    def __str__(self):
        return f"{self.user.full_phone_number}'s Wallet ({self.currency})"

    @property
    def balance(self):
        """Returns the balance in euros (or equivalent currency) as a Decimal"""
        return Decimal(str(self.balance_cents)) / Decimal('100')

    @property
    def currency_name(self):
        """Returns the full currency name"""
        return self.CURRENCY_NAMES.get(self.currency, self.currency)

    @balance.setter
    def balance(self, value):
        """Sets the balance in euros (or equivalent currency)"""
        self.balance_cents = int(Decimal(str(value)) * 100)

    def add_balance(self, amount):
        """Adds an amount to the balance atomically"""
        from django.db.models import F
        amount_cents = int(Decimal(str(amount)) * 100)
        self.balance_cents = F('balance_cents') + amount_cents
        self.save(update_fields=['balance_cents'])
        self.refresh_from_db()
        logger.info("wallet_balance_added_atomic", user_id=str(self.user.id), amount=amount, new_balance=self.balance, currency=self.currency)

    def subtract_balance(self, amount):
        """Subtracts an amount from the balance atomically.

        Lève ValidationError si le solde est insuffisant : on veut une erreur
        applicative propre (400) plutôt qu'une IntegrityError brute sur la
        contrainte DB `positive_balance_constraint` au milieu d'une transaction
        (qui remonterait en 500 et casserait le flux). La contrainte DB reste le
        garde-fou ultime contre les races.
        """
        from django.db.models import F
        from django.core.exceptions import ValidationError
        amount_cents = int(Decimal(str(amount)) * 100)

        if self.balance_cents < amount_cents:
            logger.warning(
                "insufficient_balance",
                user_id=str(self.user.id),
                balance=self.balance,
                required=amount
            )
            raise ValidationError(
                f"Solde insuffisant (requis: {amount}, disponible: {self.balance})"
            )

        self.balance_cents = F('balance_cents') - amount_cents
        self.save(update_fields=['balance_cents'])
        self.refresh_from_db()
        logger.info("wallet_balance_subtracted_atomic", user_id=str(self.user.id), amount=amount, new_balance=self.balance, currency=self.currency)

    @staticmethod
    def get_currency_from_phone_number(phone_number):
        """
        Determines the currency based on the phone number country
        
        Args:
            phone_number: Numéro de téléphone au format E.164
            
        Returns:
            str: Code devise (EUR, XAF, XOF, NGN, etc.)
        """
        
        try:
            # Parse the number to get the country code
            parsed = phonenumbers.parse(phone_number, None)
            
            # Use region code (ex: 'FR', 'CM', 'SN') directly
            region_code = phonenumbers.region_code_for_number(parsed)
            
            # Country -> Currency mapping (Africa / Europe)
            currency_map = {
                # North Africa
                'MA': 'MAD', 'DZ': 'DZD', 'TN': 'TND', 'EG': 'EGP',
                
                # Euro Zone
                'FR': 'EUR', 'DE': 'EUR', 'IT': 'EUR', 'ES': 'EUR', 
                'BE': 'EUR', 'NL': 'EUR', 'PT': 'EUR', 'IE': 'EUR',
                
                # Francophone Africa (XAF - CEMAC)
                'CM': 'XAF', 'GA': 'XAF', 'CF': 'XAF', 'TD': 'XAF', 'CG': 'XAF',
                
                # Francophone Africa (XOF - BCEAO)
                'CI': 'XOF', 'SN': 'XOF', 'ML': 'XOF', 'BJ': 'XOF', 'BF': 'XOF', 'TG': 'XOF', 'NE': 'XOF',
                
                # Anglophone Africa / Others
                'NG': 'NGN', 'GH': 'GHS', 'KE': 'KES', 'ZA': 'ZAR', 'TZ': 'TZS', 'UG': 'UGX', 'RW': 'RWF', 'ZM': 'ZMW'
            }
            
            detected_currency = currency_map.get(region_code, 'EUR')
            
            return detected_currency

            
        except Exception as e:
            logger.warning("currency_detection_failed", phone_number=phone_number, error=str(e))
            return 'EUR'

    def save(self, *args, **kwargs):
        # Automatically determines the currency if not defined
        if not self.currency and self.user:
            self.currency = self.get_currency_from_phone_number(self.user.full_phone_number)
        super().save(*args, **kwargs)


class PaymentMethod(models.Model):
    """
    Payment methods saved by the user
    Avoids re-entering information for each transaction
    """
    PAYMENT_METHOD_TYPES = (
        ('card', 'Credit Card'),
        ('bank_account', 'Bank Account'),
        ('orange_money', 'Orange Money'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payment_methods'
    )
    
    # Payment method type
    method_type = models.CharField(max_length=20, choices=PAYMENT_METHOD_TYPES)
    
    # Name/label given by the user (ex: "My main card", "BNP Account")
    label = models.CharField(max_length=100, help_text="User-given name")
    
    # Credit card information (stored securely)
    card_last_four = models.CharField(max_length=4, blank=True, null=True, help_text="Last 4 digits")
    card_brand = models.CharField(max_length=50, blank=True, null=True, help_text="Visa, Mastercard, etc.")
    card_expiry_month = models.IntegerField(blank=True, null=True, help_text="Expiry month (1-12)")
    card_expiry_year = models.IntegerField(blank=True, null=True, help_text="Expiry year")
    # Note: We NEVER store the full number or CVV for security reasons
    
    # Bank account information
    # Encrypted for security (PCI/Privacy)
    account_number = EncryptedCharField(max_length=150, blank=True, null=True, help_text="Account number (Encrypted)")
    account_number_last_four = models.CharField(max_length=4, blank=True, null=True, help_text="Last 4 digits")
    bank_code = models.CharField(max_length=20, blank=True, null=True, help_text="Bank code")
    bank_name = models.CharField(max_length=200, blank=True, null=True, help_text="Bank name")
    account_name = models.CharField(max_length=200, blank=True, null=True, help_text="Account holder name")
    bank_country = models.CharField(max_length=2, blank=True, null=True, help_text="Bank country code")
    
    # Orange Money information
    orange_money_number = EncryptedCharField(max_length=100, blank=True, null=True, help_text="Orange Money number (Encrypted)")
    
    # Métadonnées
    is_default = models.BooleanField(default=False, help_text="Default method for this type")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    
    # Référence Flutterwave (si applicable)
    flutterwave_payment_method_id = models.CharField(max_length=100, blank=True, null=True)
    flutterwave_recipient_id = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        db_table = "payment_methods"
        verbose_name = "Payment Method"
        verbose_name_plural = "Payment Methods"
        indexes = [
            models.Index(fields=['user', 'method_type', 'is_active']),
            models.Index(fields=['user', 'is_default']),
        ]

    def __str__(self):
        if self.method_type == 'card':
            return f"{self.label} - {self.card_brand or 'Card'} ****{self.card_last_four}"
        elif self.method_type == 'bank_account':
            return f"{self.label} - {self.bank_name or 'Bank'} ****{self.account_number_last_four}"
        elif self.method_type == 'orange_money':
            return f"{self.label} - {self.orange_money_number}"
        return self.label

    def mark_as_used(self):
        """Marks the method as used"""
        self.last_used_at = timezone.now()
        self.save(update_fields=['last_used_at'])


class Transaction(models.Model):
    """
    Financial transaction (deposit or withdrawal)
    """

    TRANSACTION_TYPES = (
        ('deposit', 'Deposit'),
        ('withdrawal', 'Withdrawal'),
        ('refund', 'Refund'),
        ('p2p_debit', 'P2P Debit'),
        ('p2p_credit', 'P2P Credit'),
    )

    PAYMENT_METHODS = (
        ('card', 'Credit Card'),
        ('orange_money', 'Orange Money'),
        ('internal', 'Internal (Wallet)'),
    )

    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    
    # Link to saved payment method (optional)
    payment_method_saved = models.ForeignKey(
        PaymentMethod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions',
        help_text="Saved payment method used"
    )

    # Type and method
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)

    # Transaction currency (inherits from wallet currency)
    currency = models.CharField(max_length=3, help_text="Transaction currency")

    # Amounts in local currency (in cents for precision)
    amount_cents = models.BigIntegerField(help_text="Amount in cents in local currency")
    fee_cents = models.BigIntegerField(default=0, help_text="Fees in cents in local currency")

    # Conversion rate if necessary (to EUR for calculations)
    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Conversion rate to EUR (if applicable)"
    )

    # Status and tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    flutterwave_reference = models.CharField(max_length=100, blank=True, null=True)
    flutterwave_transaction_id = models.CharField(max_length=100, blank=True, null=True)
    flutterwave_event_id = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        unique=True,
        db_index=True,
        help_text="Unique ID for the Flutterwave webhook event for idempotency"
    )

    # User metadata
    user_ip = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)

    # Method-specific payment information
    card_last_four = models.CharField(max_length=4, blank=True, null=True)  # For card
    orange_money_number = models.CharField(max_length=20, blank=True, null=True)  # For Orange Money

    # Error messages
    error_message = models.TextField(blank=True, null=True)
    error_code = models.CharField(max_length=50, blank=True, null=True)

    # Security: Indicates if the wallet balance has already been impacted
    balance_adjusted = models.BooleanField(default=False, help_text="True if the wallet balance has been updated")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Additional data (Transfer proof, Bank details, Rates, etc.)
    transfer_proof = models.CharField(max_length=255, blank=True, null=True, help_text="Payment proof (Flutterwave)")
    extra_data = models.JSONField(default=dict, blank=True, help_text="Additional data (JSON)")

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
        """Amount in local currency (for compatibility)"""
        return self.amount_cents / 100

    @property
    def fee_euros(self):
        """Fees in local currency"""
        return self.fee_cents / 100

    def save(self, *args, **kwargs):
        # Inherits from wallet currency
        if not self.currency and self.wallet:
            self.currency = self.wallet.currency

        # Completion timestamp
        if self.status == 'completed' and not self.completed_at:
            self.completed_at = timezone.now()
        elif self.status != 'completed' and self.completed_at:
            self.completed_at = None

        super().save(*args, **kwargs)

    def mark_completed(self):
        """Marks the transaction as completed with protection against concurrent access"""
        from django.db import transaction as db_transaction
        
        with db_transaction.atomic():
            # Database row locking to prevent two processes from processing
            # the same transaction simultaneously (ex: two successive webhooks)
            tx = Transaction.objects.select_for_update().get(pk=self.id)
            
            if tx.status == 'completed':
                logger.warning(
                    "transaction_already_completed",
                    transaction_id=str(tx.id),
                    current_status=tx.status
                )
                return
            
            tx.status = 'completed'
            tx.completed_at = timezone.now()
            
            # Updates the wallet balance only if it hasn't been updated already
            if not tx.balance_adjusted:
                from decimal import Decimal
                if tx.transaction_type in ['deposit', 'refund', 'p2p_credit']:
                    tx.wallet.add_balance(tx.amount_euros)
                    tx.balance_adjusted = True
                elif tx.transaction_type in ['withdrawal', 'p2p_debit']:
                    # Debit amount + fees (fees are usually 0 for p2p)
                    total_deduct = (Decimal(tx.amount_cents) + Decimal(tx.fee_cents)) / 100
                    tx.wallet.subtract_balance(total_deduct)
                    tx.balance_adjusted = True

            tx.save()
            
            # Update the current instance (self) to reflect changes
            self.status = tx.status
            self.completed_at = tx.completed_at
            self.balance_adjusted = tx.balance_adjusted

    def mark_failed(self, error_message=None, error_code=None):
        """Marks the transaction as failed"""
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
        """Marks the transaction as cancelled"""
        self.status = 'cancelled'
        if reason:
            self.error_message = reason
        if notes:
            # Store notes in error_message if no reason, or in a dedicated field if available
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
