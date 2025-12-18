from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User, KYCDocument
import phonenumbers
from phonenumbers.phonenumberutil import NumberParseException

# POUR NUMERO DE TÉLÉPHONE ET CODE PAYS
class CountryCodeField(serializers.CharField):
    """Champ personnalisé pour valider le code pays"""
    
    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        
        # S'assurer que le code pays commence par +
        if not data.startswith('+'):
            data = '+' + data
            
        return data
    
    def to_representation(self, value):
        return value

class PhoneNumberSerializer(serializers.Serializer):
    """Serializer pour l'entrée du numéro de téléphone"""
    
    phone_number = serializers.CharField(max_length=20, min_length=8)
    country_code = CountryCodeField(max_length=5)
    
    def validate_phone_number(self, value):
        """Valider que c'est un numéro valide"""
        # Supprimer les espaces et caractères spéciaux
        cleaned = ''.join(filter(str.isdigit, value))
        return cleaned
    
    def validate(self, data):
        """Valider l'ensemble des données"""
        country_code = data.get('country_code')
        phone_number = data.get('phone_number')
        
        # Valider avec la librairie phonenumbers
        try:
            parsed_number = phonenumbers.parse(f"{country_code}{phone_number}")
            
            if not phonenumbers.is_valid_number(parsed_number):
                raise serializers.ValidationError({
                    "phone_number": "Numéro de téléphone invalide"
                })
                
        except NumberParseException:
            raise serializers.ValidationError({
                "phone_number": "Format de numéro invalide"
            })
        
        return data

class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer pour afficher/modifier le profil utilisateur"""
    
    full_phone = serializers.ReadOnlyField()
    
    class Meta:
        model = User
        fields = [
            'id', 'phone_number', 'country_code', 'full_phone',
            'first_name', 'last_name', 'email', 'kyc_status',
            'is_verified', 'date_joined'
        ]
        read_only_fields = [
            'id', 'phone_number', 'country_code', 'full_phone',
            'kyc_status', 'is_verified', 'date_joined'
        ]

class KYCDocumentSerializer(serializers.ModelSerializer):
    """Serializer pour les documents KYC"""
    
    class Meta:
        model = KYCDocument
        fields = [
            'id', 'document_type', 'front_image', 
            'back_image', 'selfie_image', 'created_at', 'verified'
        ]
        read_only_fields = ['id', 'created_at', 'verified']
    
    def validate(self, data):
        """Validation personnalisée"""
        # Vérifier qu'au moins le recto est fourni
        if not data.get('front_image'):
            raise serializers.ValidationError({
                "front_image": "L'image recto est obligatoire"
            })
        
        return data

class KYCVerificationSerializer(serializers.Serializer):
    """Serializer pour soumettre la vérification KYC"""
    
    # document_type = serializers.ChoiceField(choices=KYCDocument.DOCUMENT_TYPES)
    # front_image = serializers.ImageField()
    # back_image = serializers.ImageField(required=False, allow_null=True)
    # selfie_image = serializers.ImageField(required=False, allow_null=True)
    
    document_type = serializers.ChoiceField(choices=KYCDocument.DOCUMENT_TYPES)
    front_image = serializers.CharField()  # Change de ImageField à CharField temporairement
    back_image = serializers.CharField(required=False, allow_null=True)  # Pareil
    selfie_image = serializers.CharField(required=False, allow_null=True)  # Pareil
    
    def create(self, validated_data):
        """Créer le document KYC"""
        request = self.context.get('request')
        user = request.user
        
        # Créer le document
        document = KYCDocument.objects.create(
            user=user,
            **validated_data
        )
        
        # Mettre à jour le statut de l'utilisateur
        user.kyc_status = 'pending'
        user.kyc_submitted_at = serializers.DateTimeField().to_representation(
            serializers.DateTimeField().to_internal_value(None)
        )
        user.save()
        
        return document

class AccountDeletionSerializer(serializers.Serializer):
    """Serializer pour la suppression de compte"""
    
    confirmation = serializers.CharField(
        required=True,
        help_text="Tapez 'SUPPRIMER MON COMPTE' pour confirmer"
    )
    
    def validate_confirmation(self, value):
        """Valider la confirmation"""
        if value != "SUPPRIMER MON COMPTE":
            raise serializers.ValidationError(
                "Vous devez taper exactement 'SUPPRIMER MON COMPTE' pour confirmer"
            )
        return value
        
# POUR L'AUTHENTIFICATION PAR TÉLÉPHONE ET OTP
class PhoneAuthSerializer(serializers.Serializer):
    """Serializer pour l'authentification par téléphone"""
    phone_number = serializers.CharField(max_length=20, min_length=8)
    country_code = CountryCodeField(max_length=5)
    
    def validate_phone_number(self, value):
        """Nettoyer le numéro"""
        return ''.join(filter(str.isdigit, value))

class OTPSerializer(serializers.Serializer):
    """Serializer pour la vérification OTP"""
    phone_number = serializers.CharField(max_length=20)
    otp = serializers.CharField(min_length=6, max_length=6)
    
    def validate_otp(self, value):
        """Valider que c'est 6 chiffres"""
        if not value.isdigit():
            raise serializers.ValidationError("L'OTP doit contenir seulement des chiffres")
        return value