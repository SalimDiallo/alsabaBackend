from django.db import models
from django.conf import settings
from Offer.models import Offer
import uuid

class UserPreference(models.Model):
    """
    Modèle ML: Stocke les habitudes de trading de l'utilisateur.
    Mis à jour automatiquement après chaque transaction terminée.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='preferences')
    
    # Intérêts Dominants
    # "L'utilisateur aime vendre du..."
    preferred_currency_sell = models.CharField(max_length=3, blank=True, null=True)
    # "L'utilisateur aime acheter du..."
    preferred_currency_buy = models.CharField(max_length=3, blank=True, null=True)
    
    # Capacité financière moyenne (en centimes)
    avg_transaction_amount_cents = models.BigIntegerField(default=0)
    
    # Méta-données pour le scoring
    total_transactions_count = models.IntegerField(default=0)
    last_active_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Prefs for {self.user}"

