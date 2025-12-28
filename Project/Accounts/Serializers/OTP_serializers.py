from rest_framework import serializers
import phonenumbers
from django.core.cache import cache
from django.utils import timezone
from ..models import User

class PhoneAuthSerializer(serializers.Serializer):
    """Validation pour l'envoi de code OTP"""
    phone_number = serializers.CharField(max_length=20, trim_whitespace=True)
    country_code = serializers.CharField(
        max_length=5, 
        default="+33", 
        required=False,
        help_text="Code pays par défaut: +33 (France)"
    )
    
    def validate(self, data):
        phone = data.get('phone_number').strip()
        country_code = data.get('country_code', '+33').strip()
        
        # Formatage automatique
        if not phone.startswith('+'):
            if phone.startswith('0'):
                phone = country_code + phone[1:]
            else:
                phone = country_code + phone
        
        # Validation avec phonenumbers
        try:
            parsed = phonenumbers.parse(phone, None)
            
            if not phonenumbers.is_valid_number(parsed):
                raise serializers.ValidationError({
                    "phone_number": "Numéro de téléphone invalide"
                })
            
            # Vérifier le type de ligne
            number_type = phonenumbers.number_type(parsed)
            if number_type == phonenumbers.PhoneNumberType.PREMIUM_RATE:
                raise serializers.ValidationError({
                    "phone_number": "Les numéros surtaxés ne sont pas autorisés"
                })
            
            # Format E.164 standardisé
            formatted = phonenumbers.format_number(
                parsed, 
                phonenumbers.PhoneNumberFormat.E164
            )
            
            # Mettre à jour les données validées
            data['phone_number'] = formatted
            data['country_code'] = '+' + str(parsed.country_code)
            data['raw_phone'] = phone  # Pour le debug
            
            return data
            
        except phonenumbers.NumberParseException:
            raise serializers.ValidationError({
                "phone_number": "Format invalide. Utilisez: +33612345678 ou 0612345678"
            })


class VerifyOTPSerializer(serializers.Serializer):
    """Validation pour la vérification de code OTP"""
    phone_number = serializers.CharField(max_length=20)
    code = serializers.CharField(min_length=6, max_length=6, trim_whitespace=True)
    session_key = serializers.CharField(required=False)  # Nouveau champ
    
    def validate_code(self, value):
        """Validation du code OTP"""
        if not value.isdigit():
            raise serializers.ValidationError("Le code doit contenir uniquement des chiffres")
        return value
    
    def validate(self, data):
        """Validation croisée"""
        phone_number = data.get('phone_number')
        session_key = data.get('session_key')
        
        # Si session_key fournie, vérifier la cohérence
        if session_key:
            session_data = cache.get(session_key)
            if not session_data:
                raise serializers.ValidationError({
                    "session_key": "Session expirée ou invalide"
                })
            
            # Vérifier que le phone_number correspond
            if session_data.get('phone_number') != phone_number:
                raise serializers.ValidationError({
                    "phone_number": "Incohérence avec la session"
                })
        
        return data


class ResendOTPSerializer(serializers.Serializer):
    """Validation pour le renvoi de code OTP"""
    session_key = serializers.CharField()
    
    def validate_session_key(self, value):
        """Vérifie que la session existe"""
        session_data = cache.get(value)
        if not session_data:
            raise serializers.ValidationError("Session expirée")
        return value


class UserSerializer(serializers.ModelSerializer):
    """Sérialiseur utilisateur enrichi"""
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
            'phone_number',
            'country_code',
            'kyc_status',
            'kyc_status_display',
            'is_verified',
            'has_kyc_documents',
            'profile_complete',
            'first_name',
            'last_name',
            'email',
            'date_joined',
            'last_login'
        ]
        read_only_fields = fields
    
    def get_has_kyc_documents(self, obj):
        return obj.kyc_documents.exists() if hasattr(obj, 'kyc_documents') else False
    
    def get_profile_complete(self, obj):
        """Vérifie si le profil est complété"""
        return bool(obj.first_name and obj.last_name and obj.email)