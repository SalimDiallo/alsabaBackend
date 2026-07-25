from django.contrib import admin
from .models import User, KYCDocument, WebhookAuditLog


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'full_phone_number',
        'phone_verified',          # ← Nouveau champ
        'kyc_status',
        'is_active',
        'is_staff',
        'date_joined'
    ]
    list_filter = [
        'phone_verified',          # ← Remplace 'is_verified'
        'kyc_status',
        'is_active',
        'is_staff'
    ]
    search_fields = ['full_phone_number', 'phone_number']
    ordering = ['-date_joined']

@admin.register(KYCDocument)
class KYCDocumentAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'document_type',
        'verification_status',     # ← Nouveau champ plus précis (pending/approved/rejected)
        'created_at',
        'verified_at'
    ]
    list_filter = [
        'document_type',
        'verification_status',     # ← Remplace 'verified'
    ]
    search_fields = ['user__full_phone_number']
    readonly_fields = ['created_at', 'verified_at']


@admin.register(WebhookAuditLog)
class WebhookAuditLogAdmin(admin.ModelAdmin):
    list_display = [
        'request_id',
        'didit_status',
        'webhook_status',
        'signature_valid',
        'user',
        'processing_duration_ms',
        'ip_address',
        'created_at'
    ]
    list_filter = [
        'webhook_status',
        'signature_valid',
        'didit_status',
        'created_at'
    ]
    search_fields = ['request_id', 'ip_address', 'user__full_phone_number']
    readonly_fields = [
        'id',
        'request_id',
        'didit_status',
        'ip_address',
        'user_agent',
        'payload_size',
        'signature_valid',
        'signature_received',
        'webhook_status',
        'processing_duration_ms',
        'user',
        'error_message',
        'raw_payload',
        'created_at'
    ]
    ordering = ['-created_at']
    
    def has_add_permission(self, request):
        # Les logs sont créés automatiquement, pas d'ajout manuel
        return False
    
    def has_change_permission(self, request, obj=None):
        # Les logs sont en lecture seule
        return False
