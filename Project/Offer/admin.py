from django.contrib import admin
from .models import Offer, EscrowLock, AuditLog

@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'amount_sell', 'currency_sell', 'status', 'created_at')
    list_filter = ('status', 'currency_sell', 'currency_buy')
    search_fields = ('user__phone_number', 'amount_sell_cents')
    readonly_fields = ('rate', 'accepted_by', 'accepted_at')

@admin.register(EscrowLock)
class EscrowLockAdmin(admin.ModelAdmin):
    list_display = ('id', 'offer', 'user', 'amount_cents', 'status', 'expires_at')
    list_filter = ('status', 'currency')
    search_fields = ('offer__id', 'user__phone_number')

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'action', 'user_id', 'offer_id')
    list_filter = ('action',)
    search_fields = ('user_id', 'offer_id', 'action')
    # Les logs d'audit ne doivent être ni modifiables ni supprimables
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
