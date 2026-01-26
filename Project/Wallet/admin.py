from django.contrib import admin
from .models import Wallet, Transaction


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'balance', 'currency', 'is_active', 'created_at']
    list_filter = ['is_active', 'currency', 'created_at']
    search_fields = ['user__full_phone_number', 'user__email']
    readonly_fields = ['id', 'balance_cents', 'created_at', 'updated_at']

    def balance(self, obj):
        symbol = self._get_currency_symbol(obj.currency)
        return f"{obj.balance} {symbol}"
    balance.short_description = "Solde"

    def _get_currency_symbol(self, currency):
        symbols = {
            'EUR': '€', 'XAF': 'FCFA', 'XOF': 'FCFA', 'NGN': '₦',
            'GHS': '₵', 'KES': 'KSh', 'ZAR': 'R'
        }
        return symbols.get(currency, currency)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'wallet', 'transaction_type', 'payment_method',
        'amount_euros', 'currency', 'fee_euros', 'status', 'created_at'
    ]
    list_filter = [
        'transaction_type', 'payment_method', 'status', 'currency', 'created_at'
    ]
    search_fields = [
        'wallet__user__full_phone_number',
        'flutterwave_reference',
        'flutterwave_transaction_id'
    ]
    readonly_fields = [
        'id', 'amount_cents', 'fee_cents', 'created_at', 'updated_at', 'completed_at'
    ]

    def amount_euros(self, obj):
        symbol = self._get_currency_symbol(obj.currency)
        return f"{obj.amount_euros} {symbol}"
    amount_euros.short_description = "Montant"

    def fee_euros(self, obj):
        symbol = self._get_currency_symbol(obj.currency)
        return f"{obj.fee_euros} {symbol}"
    fee_euros.short_description = "Frais"

    def wallet_user(self, obj):
        return obj.wallet.user.full_phone_number
    wallet_user.short_description = "Utilisateur"

    def _get_currency_symbol(self, currency):
        symbols = {
            'EUR': '€', 'XAF': 'FCFA', 'XOF': 'FCFA', 'NGN': '₦',
            'GHS': '₵', 'KES': 'KSh', 'ZAR': 'R'
        }
        return symbols.get(currency, currency)
