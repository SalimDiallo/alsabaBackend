"""
Interface d'administration Django pour le wallet
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import Currency, Wallet, Transaction  # ← IMPORT RELATIF CORRECT


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    """
    Admin pour les devises
    """
    list_display = ('code', 'name', 'symbol', 'decimal_places', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name')
    ordering = ('code',)


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    """
    Admin pour les wallets
    """
    list_display = ('id_short', 'user_email', 'currency', 'balance_display', 
                    'available_balance_display', 'is_active', 'created_at')
    list_filter = ('is_active', 'currency', 'created_at')
    search_fields = ('user__email', 'user__full_phone_number', 'id')
    readonly_fields = ('id', 'created_at', 'updated_at', 'last_activity')
    ordering = ('-created_at',)
    
    fieldsets = (
        ('Informations', {
            'fields': ('id', 'user', 'currency', 'is_active')
        }),
        ('Soldes', {
            'fields': ('balance', 'available_balance')
        }),
        ('Dates', {
            'fields': ('created_at', 'updated_at', 'last_activity')
        }),
    )
    
    def id_short(self, obj):
        """Affiche un ID raccourci"""
        return str(obj.id)[:8]
    id_short.short_description = 'ID'
    
    def user_email(self, obj):
        """Affiche l'email de l'utilisateur"""
        return obj.user.email or obj.user.full_phone_number
    user_email.short_description = 'Utilisateur'
    
    def balance_display(self, obj):
        """Affiche le solde formaté"""
        return f"{obj.balance} {obj.currency.code}"
    balance_display.short_description = 'Solde'
    
    def available_balance_display(self, obj):
        """Affiche le solde disponible formaté"""
        return f"{obj.available_balance} {obj.currency.code}"
    available_balance_display.short_description = 'Solde disponible'


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """
    Admin pour les transactions
    """
    list_display = ('id_short', 'wallet_info', 'type_display', 'amount_display',
                    'status_display', 'payment_method_display', 'created_at')
    list_filter = ('transaction_type', 'status', 'payment_method', 'created_at')
    search_fields = ('reference', 'external_reference', 'wallet__user__email')
    readonly_fields = ('id', 'created_at', 'completed_at')
    ordering = ('-created_at',)
    
    fieldsets = (
        ('Informations', {
            'fields': ('id', 'wallet', 'reference', 'external_reference')
        }),
        ('Transaction', {
            'fields': ('transaction_type', 'status', 'payment_method', 'description')
        }),
        ('Montants', {
            'fields': ('amount', 'fee', 'net_amount')
        }),
        ('Dates', {
            'fields': ('created_at', 'completed_at')
        }),
        ('Métadonnées', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
    )
    
    def id_short(self, obj):
        """Affiche un ID raccourci"""
        return str(obj.id)[:8]
    id_short.short_description = 'ID'
    
    def wallet_info(self, obj):
        """Affiche les infos du wallet"""
        user = obj.wallet.user
        return f"{user.email or user.full_phone_number} ({obj.wallet.currency.code})"
    wallet_info.short_description = 'Wallet'
    
    def type_display(self, obj):
        """Affiche le type avec couleur"""
        colors = {
            'DEPOSIT': 'green',
            'WITHDRAWAL': 'orange',
        }
        color = colors.get(obj.transaction_type, 'gray')
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.get_transaction_type_display()
        )
    type_display.short_description = 'Type'
    
    def amount_display(self, obj):
        """Affiche le montant formaté"""
        return f"{obj.amount} {obj.wallet.currency.code}"
    amount_display.short_description = 'Montant'
    
    def status_display(self, obj):
        """Affiche le statut avec couleur"""
        colors = {
            'COMPLETED': 'green',
            'PENDING': 'orange',
            'FAILED': 'red',
            'CANCELLED': 'gray',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.get_status_display()
        )
    status_display.short_description = 'Statut'
    
    def payment_method_display(self, obj):
        """Affiche la méthode de paiement"""
        return obj.get_payment_method_display() if obj.payment_method else '-'
    payment_method_display.short_description = 'Méthode'