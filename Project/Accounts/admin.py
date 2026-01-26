from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, KYCDocument
from .models import User, KYCDocument

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