from rest_framework import serializers
from .models import Notification, Device

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'title', 'body', 'notification_type', 'data', 'is_read', 'created_at']
        read_only_fields = ['id', 'title', 'body', 'notification_type', 'data', 'created_at']

    @staticmethod
    def setup_eager_loading(queryset):
        return queryset  # Pas de relations à charger pour le moment, mais prêt pour le futur



class DeviceSerializer(serializers.ModelSerializer):
    phone_number = serializers.CharField(
        max_length=20,
        required=False,
        allow_null=True,
        help_text="Numéro de téléphone au format E.164 (ex: +221771234567)"
    )
    
    class Meta:
        model = Device
        fields = ['id', 'phone_number', 'registration_id', 'platform', 'is_active', 'created_at', 'last_used_at']
        read_only_fields = ['id', 'created_at', 'last_used_at']

    def validate_phone_number(self, value):
        """Valide le format E.164 du numéro de téléphone s'il est fourni"""
        if not value:
            return value
        import re
        if not re.match(r'^\+[1-9]\d{1,14}$', value):
            raise serializers.ValidationError(
                'Le numéro doit être au format E.164 (ex: +221771234567)'
            )
        return value

    def create(self, validated_data):
        user = self.context['request'].user
        phone_number = validated_data.get('phone_number')
        registration_id = validated_data.get('registration_id')

        if not phone_number and not registration_id:
            raise serializers.ValidationError("Vous devez fournir soit un phone_number, soit un registration_id.")

        # Logique de recherche pour éviter les doublons
        # On cherche d'abord par registration_id s'il existe (prioritaire pour le Push)
        device = None
        if registration_id:
            device = Device.objects.filter(registration_id=registration_id).first()
        
        # Sinon par phone_number
        if not device and phone_number:
            device = Device.objects.filter(user=user, phone_number=phone_number).first()

        if device:
            # Mise à jour de l'existant
            device.is_active = True
            if phone_number:
                device.phone_number = phone_number
            if registration_id:
                device.registration_id = registration_id
            device.save()
        else:
            # Création
            device = Device.objects.create(user=user, **validated_data)
            
        return device
