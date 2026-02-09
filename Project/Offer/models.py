from django.db import models
from django.conf import settings
import uuid
from django.utils import timezone
from fernet_fields import EncryptedCharField, EncryptedTextField, EncryptedIntegerField



class Offer(models.Model):
    """
    P2P exchange offer published by a user (A1).
    """
    STATUS_CHOICES = (
        ('OPEN', 'Open'),
        ('ACCEPTED', 'Accepted (Waiting for funds)'),
        ('LOCKED', 'Funds Locked (Escrow)'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
        ('EXPIRED', 'Expired'),
        ('DISPUTE', 'In Dispute'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='offers')
    
    # What the user is selling (Source)
    amount_sell_cents = models.BigIntegerField(help_text="Amount sold in cents")
    currency_sell = models.CharField(max_length=3)
    
    # What the user wants to receive (Destination)
    amount_buy_cents = models.BigIntegerField(help_text="Desired amount in cents")
    currency_buy = models.CharField(max_length=3)
    
    # Implicit exchange rate stored for reference
    rate = models.DecimalField(max_digits=10, decimal_places=6, help_text="Rate: 1 Unit Sell = X Unit Buy")
    
    # Beneficiaries - ENCRYPTED for PCI-DSS security
    # Stored as encrypted JSON (EncryptedTextField)
    _beneficiary_data_encrypted = EncryptedTextField(
        blank=True, 
        default='{}',
        help_text="Beneficiary designated by the seller (B2) - Encrypted data",
        db_column='beneficiary_data'
    )
    
    _accepted_beneficiary_data_encrypted = EncryptedTextField(
        blank=True, 
        default='{}',
        help_text="Beneficiary designated by the buyer (B1) - Encrypted data",
        db_column='accepted_beneficiary_data'
    )

    # Beneficiary confirmations
    b1_confirmed = models.BooleanField(default=False, help_text="Beneficiary B1 has confirmed receipt/participation")
    b2_confirmed = models.BooleanField(default=False, help_text="Beneficiary B2 has confirmed receipt/participation")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN', db_index=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()
    
    # Counterparty (A2) - Filled when offer is accepted
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
    
    # Properties to manage JSON serialization/deserialization
    @property
    def beneficiary_data(self):
        """Returns the decrypted beneficiary data as a dict"""
        import json
        if not self._beneficiary_data_encrypted:
            return {}
        try:
            return json.loads(self._beneficiary_data_encrypted)
        except (json.JSONDecodeError, TypeError):
            return {}
    
    @beneficiary_data.setter
    def beneficiary_data(self, value):
        """Stores the encrypted beneficiary data"""
        import json
        if value is None:
            value = {}
        self._beneficiary_data_encrypted = json.dumps(value)
    
    @property
    def accepted_beneficiary_data(self):
        """Returns the decrypted accepted beneficiary data as a dict"""
        import json
        if not self._accepted_beneficiary_data_encrypted:
            return {}
        try:
            return json.loads(self._accepted_beneficiary_data_encrypted)
        except (json.JSONDecodeError, TypeError):
            return {}
    
    @accepted_beneficiary_data.setter
    def accepted_beneficiary_data(self, value):
        """Stores the encrypted accepted beneficiary data"""
        import json
        if value is None:
            value = {}
        self._accepted_beneficiary_data_encrypted = json.dumps(value)

    @property
    def amount_sell(self):
        return self.amount_sell_cents / 100.0

    @property
    def amount_buy(self):
        return self.amount_buy_cents / 100.0


class EscrowLock(models.Model):
    """
    Security lock on funds.
    Represents an amount locked in the Escrow system.
    """
    STATUS_CHOICES = (
        ('LOCKED', 'Locked'),
        ('RELEASED', 'Released (Transferred)'),
        ('ROLLEDBACK', 'Refunded (Cancellation)'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Link to the concerned offer
    offer = models.ForeignKey(Offer, on_delete=models.PROTECT, related_name='locks')
    
    # User who owns the locked funds (A1 or A2)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='escrow_locks')
    
    # Locked amount
    amount_cents = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='LOCKED')
    
    # Security & Integrity
    lock_hash = models.CharField(max_length=256, help_text="SHA256 hash of lock data for integrity")
    
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(help_text="Deadline before auto-rollback")
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "escrow_locks"
        indexes = [
            models.Index(fields=['status', 'user']),
        ]


class AuditLog(models.Model):
    """
    Immutable audit log for all Escrow operations.
    Chainable via previous hash.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    action = models.CharField(max_length=50) # LOCK, RELEASE, ROLLBACK, MATCH
    
    # Contextual data
    user_id = models.CharField(max_length=100, db_index=True)
    offer_id = models.CharField(max_length=100, blank=True, null=True)
    amount_cents = models.BigIntegerField(null=True)
    currency = models.CharField(max_length=3, null=True)
    
    # Complete details in JSON
    details = models.JSONField(default=dict)
    
    # Cryptographic chaining
    previous_hash = models.CharField(max_length=64, help_text="Previous log hash")
    hash = models.CharField(max_length=64, help_text="Current hash (Merkle-like)")

    class Meta:
        db_table = "escrow_audit_logs"
        ordering = ['timestamp']

# New: Model for dispute management
class Dispute(models.Model):
    """
    New: Model for offer dispute resolution.
    Allows A1 or A2 to contest an offer and invoke a resolution process.
    """
    RESOLUTION_CHOICES = (
        ('refund_a1', 'Refund A1'),
        ('refund_a2', 'Refund A2'),
        ('split', '50/50 Split'),
        ('pending', 'Pending'),
    )
    
    STATUS_CHOICES = (
        ('open', 'Open'),
        ('under_review', 'Under Review'),
        ('resolved', 'Resolved'),
        ('escalated', 'Escalated (Manual support)'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    offer = models.ForeignKey(Offer, on_delete=models.PROTECT, related_name='disputes')
    
    # Who initiated the dispute
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='disputes_initiated'
    )
    
    # Reason for the dispute
    reason = models.CharField(max_length=500)
    
    # Evidence JSON (messages, screenshots, etc.)
    evidence = models.JSONField(default=dict, blank=True)
    
    # Dispute status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open', db_index=True)
    
    # Proposed resolution
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