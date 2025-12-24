from rest_framework import serializers
import phonenumbers
from ..models import User

class PhoneAuthSerializer(serializers.Serializer):
    """Validation pour l'envoi de code"""
    phone_number = serializers.CharField(max_length=20)
    country_code = serializers.CharField(max_length=5, default="+33", required=False)
    
    def validate(self, data):
        phone = data.get('phone_number')
        country_code = data.get('country_code', '+33')
        
        # Formatage automatique
        if not phone.startswith('+'):
            phone = country_code + phone.lstrip('0')
        
        # Validation avec phonenumbers
        try:
            parsed = phonenumbers.parse(phone, None)
            if not phonenumbers.is_valid_number(parsed):
                raise serializers.ValidationError({
                    "phone_number": "Numéro de téléphone invalide"
                })
            
            # Format E.164 standardisé
            formatted = phonenumbers.format_number(
                parsed, 
                phonenumbers.PhoneNumberFormat.E164
            )
            
            data['phone_number'] = formatted
            data['country_code'] = '+' + str(parsed.country_code)
            
        except phonenumbers.NumberParseException:
            raise serializers.ValidationError({
                "phone_number": "Format invalide. Utilisez: +33612345678"
            })
        
        return data


class VerifyOTPSerializer(serializers.Serializer):
    """Validation pour la vérification de code"""
    phone_number = serializers.CharField(max_length=20)
    code = serializers.CharField(min_length=6, max_length=6)
    request_id = serializers.CharField()  # ID de la requête Didit


class UserSerializer(serializers.ModelSerializer):
    """Sérialiseur pour l'utilisateur"""
    kyc_status_display = serializers.CharField(source='get_kyc_status_display', read_only=True)
    has_kyc_documents = serializers.SerializerMethodField()
    
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
            'first_name',
            'last_name',
            'email',
            'date_joined'
        ]
        read_only_fields = fields
    
    def get_has_kyc_documents(self, obj):
        return obj.kyc_documents.exists()