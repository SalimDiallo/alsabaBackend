from django.db import models
from django.conf import settings
import uuid
from django.utils import timezone
from fernet_fields import EncryptedCharField, EncryptedTextField, EncryptedIntegerField



class Offer(models.Model):
    """
    Offre d'échange P2P publiée par un utilisateur (A1).
    """
    STATUS_CHOICES = (
        ('OPEN', 'Ouverte'),
        ('ACCEPTED', 'Acceptée (En attente de fonds)'),
        ('LOCKED', 'Fonds Bloqués (Escrow)'),
        ('COMPLETED', 'Terminée'),
        ('CANCELLED', 'Annulée'),
        ('EXPIRED', 'Expirée'),
        ('DISPUTE', 'En Litige'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='offers')
    
    # Ce que l'utilisateur vend (Source)
    amount_sell_cents = models.BigIntegerField(help_text="Montant vendu en centimes")
    currency_sell = models.CharField(max_length=3)
    
    # Ce que l'utilisateur veut recevoir (Destination)
    amount_buy_cents = models.BigIntegerField(help_text="Montant souhaité en centimes")
    currency_buy = models.CharField(max_length=3)
    
    # Taux de change implicite stocké pour référence
    rate = models.DecimalField(max_digits=10, decimal_places=6, help_text="Taux: 1 Unit Sell = X Unit Buy")
    
    # Bénéficiaires (TODO: Encrypt this field in future)
    # beneficiary_data = B2 (Ami de A1, reçoit EUR)
    beneficiary_data = models.JSONField(default=dict, blank=True, help_text="Bénéficiaire désigné par le vendeur (B2)")
    
    # accepted_beneficiary_data = B1 (Ami de A2, reçoit XOF)
    accepted_beneficiary_data = models.JSONField(default=dict, blank=True, help_text="Bénéficiaire désigné par l'acheteur (B1)")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN', db_index=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()
    
    # Partie adverse (A2) - Rempli quand l'offre est acceptée
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='accepted_offers'
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "offers"
        indexes = [
            models.Index(fields=['status', 'currency_sell', 'currency_buy']),
            models.Index(fields=['expires_at']),
        ]
        ordering = ['-created_at']

    @property
    def amount_sell(self):
        return self.amount_sell_cents / 100.0

    @property
    def amount_buy(self):
        return self.amount_buy_cents / 100.0


class EscrowLock(models.Model):
    """
    Verrou de sécurité sur les fonds.
    Représente une somme bloquée dans le système Escrow.
    """
    STATUS_CHOICES = (
        ('LOCKED', 'Verrouillé'),
        ('RELEASED', 'Libéré (Transféré)'),
        ('ROLLEDBACK', 'Remboursé (Annulation)'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Lien vers l'offre concernée
    offer = models.ForeignKey(Offer, on_delete=models.PROTECT, related_name='locks')
    
    # Utilisateur à qui appartiennent les fonds bloqués (A1 ou A2)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='escrow_locks')
    
    # Montant bloqué
    amount_cents = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='LOCKED')
    
    # Sécurité & Intégrité
    lock_hash = models.CharField(max_length=256, help_text="Hash SHA256 des données du lock pour intégrité")
    
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(help_text="Date limite avant auto-rollback")
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "escrow_locks"
        indexes = [
            models.Index(fields=['status', 'user']),
        ]


class AuditLog(models.Model):
    """
    Journal d'audit immuable pour toutes les opérations Escrow.
    Chainable via hash précédent.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    action = models.CharField(max_length=50) # LOCK, RELEASE, ROLLBACK, MATCH
    
    # Données contextuelles
    user_id = models.CharField(max_length=100, db_index=True)
    offer_id = models.CharField(max_length=100, blank=True, null=True)
    amount_cents = models.BigIntegerField(null=True)
    currency = models.CharField(max_length=3, null=True)
    
    # Détails complets en JSON
    details = models.JSONField(default=dict)
    
    # Chaînage cryptographique
    previous_hash = models.CharField(max_length=64, help_text="Hash du log précédent")
    hash = models.CharField(max_length=64, help_text="Hash actuel (Merckle like)")

    class Meta:
        db_table = "escrow_audit_logs"
        ordering = ['timestamp']

# ✅ NOUVEAU: Modèle pour la gestion des litiges
class Dispute(models.Model):
    """
    ✅ NOUVEAU: Modèle pour la résolution des litiges d'offres.
    Permet à A1 ou A2 de contester une offre et d'invoquer un processus de résolution.
    """
    RESOLUTION_CHOICES = (
        ('refund_a1', 'Remboursement A1'),
        ('refund_a2', 'Remboursement A2'),
        ('split', 'Partage 50/50'),
        ('pending', 'En attente'),
    )
    
    STATUS_CHOICES = (
        ('open', 'Ouvert'),
        ('under_review', 'Sous revue'),
        ('resolved', 'Résolu'),
        ('escalated', 'Escaladé (Support manuel)'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    offer = models.ForeignKey(Offer, on_delete=models.PROTECT, related_name='disputes')
    
    # Qui a initié le litige
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='disputes_initiated'
    )
    
    # Raison du litige
    reason = models.CharField(max_length=500)
    
    # Evidence JSON (messages, screenshots, etc.)
    evidence = models.JSONField(default=dict, blank=True)
    
    # Statut du litige
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open', db_index=True)
    
    # Résolution proposée
    resolution = models.CharField(
        max_length=20,
        choices=RESOLUTION_CHOICES,
        default='pending',
        blank=True
    )
    
    # Admin review
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='disputes_reviewed'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    admin_notes = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = "offer_disputes"
        indexes = [
            models.Index(fields=['offer', 'status']),
            models.Index(fields=['initiated_by', 'created_at']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Dispute {self.id} for Offer {self.offer.id} - {self.status}"