import uuid
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal, ROUND_DOWN
import logging

logger = logging.getLogger(__name__)


class Currency(models.Model):
    """
    Modèle pour les devises supportées par la plateforme
    Une devise par code (EUR, XOF, USD, etc.)
    """
    code = models.CharField(max_length=3, primary_key=True)  # EUR, USD, XOF
    name = models.CharField(max_length=50)
    symbol = models.CharField(max_length=5)
    decimal_places = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "wallet_currencies"
        verbose_name = "Devise"
        verbose_name_plural = "Devises"
    
    def __str__(self):
        return f"{self.code} ({self.symbol})"


class Wallet(models.Model):
    """
    Portefeuille utilisateur
    Un utilisateur = un wallet avec une devise déterminée par son pays
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey('Accounts.User', on_delete=models.CASCADE, related_name='wallets')
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    
    # Soldes
    balance = models.DecimalField(
        max_digits=20, 
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    available_balance = models.DecimalField(
        max_digits=20, 
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    
    # Statut
    is_active = models.BooleanField(default=True)
    
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_activity = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = "wallets"
        verbose_name = "Portefeuille"
        verbose_name_plural = "Portefeuilles"
        unique_together = ['user', 'currency']
        indexes = [
            models.Index(fields=['user', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.user} - {self.currency.code} ({self.balance})"
    
    def save(self, *args, **kwargs):
        """
        Override de la méthode save pour :
        1. Arrondir les montants selon les décimales de la devise
        2. S'assurer de la cohérence des soldes
        """
        # Arrondir selon les décimales de la devise
        decimal_places = self.currency.decimal_places
        self.balance = self.balance.quantize(
            Decimal('0.' + '0' * decimal_places), 
            rounding=ROUND_DOWN
        )
        self.available_balance = self.available_balance.quantize(
            Decimal('0.' + '0' * decimal_places), 
            rounding=ROUND_DOWN
        )
        
        # Log de création/mise à jour
        if self.pk is None:
            logger.info(
                "wallet_created",
                wallet_id=str(self.id),
                user_id=str(self.user.id),
                currency=self.currency.code
            )
        else:
            logger.debug(
                "wallet_updated",
                wallet_id=str(self.id),
                balance=float(self.balance)
            )
        
        super().save(*args, **kwargs)


class Transaction(models.Model):
    """
    Historique des transactions de dépôt et retrait
    Toutes les opérations sont enregistrées ici
    """
    
    TRANSACTION_TYPES = (
        ('DEPOSIT', 'Dépôt'),
        ('WITHDRAWAL', 'Retrait'),
    )
    
    STATUS_CHOICES = (
        ('PENDING', 'En attente'),
        ('COMPLETED', 'Terminé'),
        ('FAILED', 'Échoué'),
        ('CANCELLED', 'Annulé'),
    )
    
    PAYMENT_METHODS = (
        ('ORANGE_MONEY', 'Orange Money'),
        ('CARD', 'Carte bancaire'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    # Montants
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    fee = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=20, decimal_places=2)  # amount - fee
    
    # Références
    reference = models.CharField(max_length=100, unique=True, db_index=True)
    external_reference = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    
    # Métadonnées
    description = models.TextField(blank=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    metadata = models.JSONField(default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = "wallet_transactions"
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"
        indexes = [
            models.Index(fields=['wallet', 'created_at']),
            models.Index(fields=['reference']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['transaction_type', 'created_at']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount} {self.wallet.currency.code}"
    
    def save(self, *args, **kwargs):
        """Override save pour le logging"""
        if self.pk is None:
            logger.info(
                "transaction_created",
                transaction_id=str(self.id),
                wallet_id=str(self.wallet.id),
                type=self.transaction_type,
                amount=float(self.amount)
            )
        super().save(*args, **kwargs)
    
    def mark_completed(self):
        """Marque la transaction comme complétée"""
        if self.status == 'PENDING':
            self.status = 'COMPLETED'
            self.completed_at = timezone.now()
            self.save()
            logger.info(
                "transaction_completed",
                transaction_id=str(self.id)
            )
    
    def mark_failed(self, reason=""):
        """Marque la transaction comme échouée"""
        self.status = 'FAILED'
        if reason:
            self.description = f"{self.description} | Échec: {reason}"
        self.save()
        logger.warning(
            "transaction_failed",
            transaction_id=str(self.id),
            reason=reason
        )