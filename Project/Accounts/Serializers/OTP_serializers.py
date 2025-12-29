# apps/auth/Serializers/OTP_serializers.py

from rest_framework import serializers
import phonenumbers
from phonenumbers import PhoneNumberFormat
from django.core.cache import cache
from ..models import User


class PhoneAuthSerializer(serializers.Serializer):
    """
    Validation pour la demande d'envoi de code OTP
    Retourne le numéro au format E.164 complet (+336...)
    """
    phone_number = serializers.CharField(max_length=20, trim_whitespace=True)
    country_code = serializers.CharField(
        max_length=5,
        required=False,
        default="+33",
        help_text="Code pays avec +, ex: +33, +1, +44"
    )

    def validate(self, data):
        raw_phone = data.get('phone_number').strip()
        country_code = data.get('country_code', '+33').strip()

        # Nettoyage et préparation du numéro
        if raw_phone.startswith('+'):
            full_input = raw_phone
        elif raw_phone.startswith('0'):
            full_input = country_code + raw_phone[1:]
        else:
            full_input = country_code + raw_phone

        try:
            parsed = phonenumbers.parse(full_input, None)

            if not phonenumbers.is_valid_number(parsed):
                raise serializers.ValidationError({
                    "phone_number": "Numéro de téléphone invalide"
                })

            # Vérification type de numéro (optionnel mais recommandé)
            number_type = phonenumbers.number_type(parsed)
            if number_type == phonenumbers.PhoneNumberType.PREMIUM_RATE:
                raise serializers.ValidationError({
                    "phone_number": "Les numéros surtaxés ne sont pas autorisés"
                })

            # Format E.164 standardisé → c'est ce qu'on utilise partout maintenant
            full_e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)

            data['phone_number'] = full_e164
            data['country_code'] = f"+{parsed.country_code}"

            return data

        except phonenumbers.NumberParseException:
            raise serializers.ValidationError({
                "phone_number": "Format invalide. Exemples valides : +33612345678, 0612345678, 0033612345678"
            })


class VerifyOTPSerializer(serializers.Serializer):
    """
    Validation pour la vérification du code OTP
    """
    phone_number = serializers.CharField(max_length=20)  # Doit être en E.164
    code = serializers.CharField(min_length=6, max_length=6, trim_whitespace=True)
    session_key = serializers.CharField(required=False, allow_blank=True)

    def validate_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("Le code doit contenir uniquement des chiffres")
        return value

    def validate_phone_number(self, value):
        # Vérification rapide que c'est bien du E.164
        if not value.startswith('+') or len(value) < 10 or len(value) > 16:
            raise serializers.ValidationError("Format du numéro invalide (doit être E.164)")
        return value

    def validate(self, data):
        phone_number = data.get('phone_number')
        session_key = data.get('session_key')

        if session_key:
            session_data = cache.get(session_key)
            if not session_data:
                raise serializers.ValidationError({
                    "session_key": "Session expirée ou invalide"
                })

            if session_data.get('full_phone_number') != phone_number:
                raise serializers.ValidationError({
                    "phone_number": "Ce numéro ne correspond pas à la session"
                })

        return data


class ResendOTPSerializer(serializers.Serializer):
    """
    Validation pour le renvoi du code OTP
    """
    session_key = serializers.CharField(required=True)

    def validate_session_key(self, value):
        session_data = cache.get(value)
        if not session_data:
            raise serializers.ValidationError("Session expirée ou invalide")
        return value


class UserSerializer(serializers.ModelSerializer):
    """
    Sérialiseur complet de l'utilisateur pour les réponses auth
    """
    kyc_status_display = serializers.CharField(
        source='get_kyc_status_display',
        read_only=True
    )
    has_kyc_documents = serializers.SerializerMethodField()
    profile_complete = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'full_phone_number',      # On expose le numéro complet
            'country_code',
            'phone_number',           # Numéro national (optionnel, pour debug ou app)
            'email',
            'first_name',
            'last_name',
            'kyc_status',
            'kyc_status_display',
            'phone_verified',
            'phone_verified_at',
            'carrier',
            'is_disposable',
            'is_voip',
            'has_kyc_documents',
            'profile_complete',
            'date_joined',
            'last_login'
        ]
        read_only_fields = fields

    def get_has_kyc_documents(self, obj):
        return obj.kyc_documents.exists()

    def get_profile_complete(self, obj):
        return bool(obj.first_name and obj.last_name and obj.email)