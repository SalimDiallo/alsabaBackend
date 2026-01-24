from django.db import models, transaction
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal
import uuid
import structlog

from Accounts.models import User  # Ton modèle User (ajuste si chemin différent)
from .utils import get_currency_code_from_phone  # Fonction de détection devise

logger = structlog.get_logger(__name__)

class Currency(models.Model):
    """
    Modèle pour les devises supportées (ISO 4217).
    Pré-rempli via migration data (EUR, MAD, XOF, etc.).
    """
    code = models.CharField(max_length=3, primary_key=True, unique=True)
    name = models.CharField(max_length=60)
    symbol = models.CharField(max_length=5)
    decimal_places = models.PositiveSmallIntegerField(default=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "currencies"
        ordering = ['code']

    def __str__(self):
        return f"{self.code} ({self.name})"


class Wallet(models.Model):
    """
    Wallet unique par utilisateur.
    - Devise auto-assignée via country_code du téléphone.
    - Solde en Decimal pour précision financière (support jusqu'à 24 chiffres, 8 décimales).
    - Locked_balance pour fonds bloqués (ex: dépôts en attente de confirmation).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)

    balance = models.DecimalField(
        max_digits=24,
        decimal_places=8,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    locked_balance = models.DecimalField(
        max_digits=24,
        decimal_places=8,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"Wallet de {self.user.full_phone_number} ({self.currency.code}) - Solde: {self.balance}"

    @property
    def available_balance(self) -> Decimal:
        """Solde utilisable (balance - locked_balance)."""
        return self.balance - self.locked_balance

    @classmethod
    def create_for_user(cls, user: User) -> 'Wallet':
        """
        Factory pour créer un wallet pour un utilisateur.
        - Détecte la devise via full_phone_number.
        - Atomicité pour éviter doublons.
        """
        with transaction.atomic():
            if hasattr(user, 'wallet'):
                logger.info("wallet_already_exists", user_id=str(user.id))
                return user.wallet

            currency_code = get_currency_code_from_phone(user.full_phone_number)
            try:
                currency = Currency.objects.get(code=currency_code)
            except Currency.DoesNotExist:
                logger.error("currency_not_found", code=currency_code)
                raise ValueError(f"Devise {currency_code} non configurée. Contactez l'admin.")

            wallet = cls.objects.create(
                user=user,
                currency=currency
            )
            logger.info("wallet_created", user_id=str(user.id), currency_code=currency_code)
            return wallet

    @transaction.atomic
    def deposit(self, amount: Decimal, method: str, reference: str = "") -> None:
        """
        Placeholder pour dépôt. Ajoute au solde.
        - Vérifie montant positif.
        - Log l'opération.
        """
        if amount <= Decimal('0.00'):
            raise ValueError("Le montant doit être positif.")
        self.balance += amount
        self.updated_at = timezone.now()
        self.save(update_fields=['balance', 'updated_at'])
        logger.info(
            "deposit_success",
            user_id=str(self.user.id),
            amount=str(amount),
            method=method,
            reference=reference,
            new_balance=str(self.balance)
        )
    @transaction.atomic
    def withdraw(self, amount: Decimal, method: str, reference: str = "") -> None:
        """
        Retire de l'argent du wallet (placeholder pour le moment).
        - Vérifie que le solde disponible est suffisant
        - Débite le solde
        - Log l'opération
        """
        if amount <= Decimal('0.00'):
            raise ValueError("Le montant du retrait doit être positif.")

        if self.available_balance < amount:
            raise ValueError(f"Solde insuffisant. Disponible : {self.available_balance}, demandé : {amount}")

        self.balance -= amount
        self.updated_at = timezone.now()
        self.save(update_fields=['balance', 'updated_at'])

        logger.info(
            "withdrawal_success",
            user_id=str(self.user.id),
            amount=str(amount),
            method=method,
            reference=reference,
            remaining_balance=str(self.balance)
        )