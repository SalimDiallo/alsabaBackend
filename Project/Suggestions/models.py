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

    # --- Profil enrichi (moteur de recommandation) ---
    # Statistiques par corridor de l'utilisateur, du point de vue "je vends X, j'achète Y".
    # Format: { "XOF>EUR": {"count": int, "volume_cents": int, "last_at": "iso"} }
    corridor_stats = models.JSONField(
        default=dict, blank=True,
        help_text="Stats par corridor 'SELL>BUY' : count, volume_cents, last_at"
    )

    # Réputation (dénormalisée pour un scoring performant)
    completed_offers_count = models.IntegerField(default=0)
    disputes_count = models.IntegerField(default=0)

    def __str__(self):
        return f"Prefs for {self.user}"

    def corridor_affinity(self, sell_currency, buy_currency):
        """
        Retourne (count, volume_cents, last_at_iso) pour le corridor 'sell>buy'
        du point de vue de l'utilisateur, ou (0, 0, None) si jamais tradé.
        """
        stats = (self.corridor_stats or {}).get(f"{sell_currency}>{buy_currency}")
        if not stats:
            return 0, 0, None
        return stats.get('count', 0), stats.get('volume_cents', 0), stats.get('last_at')

