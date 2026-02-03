# apps/auth/Serializers/OTP_serializers.py (ou profile_serializers.py)

from rest_framework import serializers
from ..models import User
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes

class ProfileSerializer(serializers.ModelSerializer):
    """
    Serializer complet pour afficher le profil de l'utilisateur connecté
    """
    kyc_status_display = serializers.CharField(
        source='get_kyc_status_display',
        read_only=True
    )

    phone_verified_display = serializers.SerializerMethodField()
    completion_percentage = serializers.SerializerMethodField()
    next_steps = serializers.SerializerMethodField()
    verification_status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'full_phone_number',
            'country_code',
            'phone_number',
            'phone_verified',
            'phone_verified_display',
            'phone_verified_at',

            # Infos personnelles
            'first_name',
            'last_name',
            'email',

            # Adresse structurée
            'city',
            'postal_code',
            'state',

            # KYC
            'kyc_status',
            'kyc_status_display',
            'kyc_verified_at',
            'kyc_submitted_at',
            'kyc_retry_count',

            # Données extraites par Didit (si KYC verified)
            'kyc_document_type',
            'kyc_document_number',
            'kyc_date_of_birth',
            'kyc_expiration_date',
            'kyc_gender',
            'kyc_nationality',
            'kyc_place_of_birth',
            'kyc_address',

            # Métadonnées compte
            'date_joined',
            'last_login',
            'is_active',

            # Champs calculés
            'completion_percentage',
            'next_steps',
            'verification_status',
        ]
        read_only_fields = fields  # Tout en lecture seule

    @extend_schema_field(OpenApiTypes.STR)
    def get_phone_verified_display(self, obj):
        return "Vérifié" if obj.phone_verified else "Non vérifié"

    @extend_schema_field(OpenApiTypes.INT)
    def get_completion_percentage(self, obj):
        """Calcule le pourcentage de complétion du profil."""
        fields = [
            (obj.phone_verified, 2),
            (obj.first_name, 1),
            (obj.last_name, 1),
            (obj.email, 1),
            (obj.kyc_status == 'verified', 2),
            (obj.kyc_document_number, 0.5),
            (obj.kyc_address, 0.5),
            (obj.city, 0.5),
            (obj.postal_code, 0.5),
            (obj.state, 0.5),
        ]
        total_possible = sum(weight for _, weight in fields)
        completed = sum(weight for condition, weight in fields if condition)
        return min(100, int((completed / total_possible) * 100)) if total_possible > 0 else 0

    @extend_schema_field(serializers.ListField(child=serializers.JSONField()))
    def get_next_steps(self, obj):
        """Détermine les prochaines étapes pour compléter le profil."""
        next_steps = []
        if not obj.email:
            next_steps.append({"action": "add_email", "priority": "high", "message": "Ajoutez votre adresse email"})
        if not obj.first_name or not obj.last_name:
            next_steps.append({"action": "complete_name", "priority": "high", "message": "Complétez votre nom et prénom"})
        if not obj.city or not obj.postal_code or not obj.state:
            next_steps.append({"action": "complete_address", "priority": "medium", "message": "Complétez vos informations d'adresse"})
        if obj.kyc_status == 'unverified':
            next_steps.append({"action": "verify_identity", "priority": "medium", "message": "Vérifiez votre identité (KYC)"})
        elif obj.kyc_status == 'rejected':
            if obj.kyc_retry_count < 3:
                next_steps.append({"action": "retry_kyc", "priority": "high", "message": "Votre vérification a été rejetée, réessayez"})
            else:
                next_steps.append({"action": "contact_support", "priority": "critical", "message": "Contactez le support pour votre vérification"})
        return next_steps

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_verification_status(self, obj):
        return {
            'phone': {
                'verified': obj.phone_verified,
                'verified_at': obj.phone_verified_at,
                'carrier': obj.carrier
            },
            'identity': {
                'status': obj.kyc_status,
                'verified_at': obj.kyc_verified_at,
                'retry_count': obj.kyc_retry_count
            }
        }


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer pour la mise à jour des informations du profil
    """
    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'email',
            'city',
            'postal_code',
            'state',
        ]

    def validate_email(self, value):
        """Vérifie l'unicité de l'email si fourni"""
        if value:
            user = self.context['request'].user
            if User.objects.filter(email=value).exclude(id=user.id).exists():
                raise serializers.ValidationError("Cette adresse email est déjà utilisée.")
        return value
