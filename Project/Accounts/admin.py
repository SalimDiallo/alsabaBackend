from django.contrib import admin

# Register your models here.

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, KYCDocument


class UserAdmin(BaseUserAdmin):
    list_display = ('phone_number', 'country_code', 'first_name', 'last_name', 
                    'kyc_status', 'is_verified', 'is_active', 'date_joined')
    list_filter = ('kyc_status', 'is_verified', 'is_active', 'is_staff')
    search_fields = ('phone_number', 'first_name', 'last_name', 'email')
    ordering = ('-date_joined',)
    
    fieldsets = (
        (None, {'fields': ('phone_number', 'password')}),
        ('Informations personnelles', {'fields': ('country_code', 'first_name', 
                                                  'last_name', 'email')}),
        ('Statut KYC', {'fields': ('kyc_status', 'kyc_submitted_at', 
                                   'kyc_verified_at', 'persona_inquiry_id')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 
                                    'groups', 'user_permissions')}),
        ('Dates importantes', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('phone_number', 'country_code', 'password1', 'password2'),
        }),
    )


class KYCDocumentAdmin(admin.ModelAdmin):
    list_display = ('user', 'document_type', 'verified', 'created_at')
    list_filter = ('document_type', 'verified')
    search_fields = ('user__phone_number', 'user__first_name', 'user__last_name')
    readonly_fields = ('created_at',)


admin.site.register(User, UserAdmin)
admin.site.register(KYCDocument, KYCDocumentAdmin)