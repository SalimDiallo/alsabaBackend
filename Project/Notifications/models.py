from django.db import models
from django.conf import settings
import uuid

class Device(models.Model):
    """
    Stocke les tokens FCM des appareils utilisateurs pour le Push Notification.
    Un utilisateur peut avoir plusieurs appareils (Tablette, Téléphone 1, Téléphone 2).
    """
    PLATFORM_CHOICES = (
        ('android', 'Android'),
        ('ios', 'iOS'),
        ('web', 'Web'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='devices')
    
    # Le token FCM unique fourni par Firebase côté client
    fcm_token = models.CharField(max_length=255, unique=True, help_text="Token Firebase Cloud Messaging")
    
    platform = models.CharField(max_length=10, choices=PLATFORM_CHOICES, default='android')
    
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "notification_devices"
        unique_together = ('user', 'fcm_token')

    def __str__(self):
        return f"{self.user} - {self.platform} ({self.fcm_token[:10]}...)"


class Notification(models.Model):
    """
    Historique des notifications in-app.
    """
    TYPE_CHOICES = (
        ('system', 'Système'),
        ('security', 'Sécurité'),
        ('transaction', 'Transaction'),
        ('offer', 'Offre P2P'),
        ('marketing', 'Promotion'),
        ('suggestion', 'Suggestion IA'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='system')
    
    title = models.CharField(max_length=255)
    body = models.TextField()
    
    # Données additionnelles pour le deep linking (ex: {'offer_id': '123', 'screen': 'offer_detail'})
    data = models.JSONField(default=dict, blank=True)
    
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = "notifications"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
        ]

    def __str__(self):
        return f"{self.title} - {self.user}"
