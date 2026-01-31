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
        help_text="Numéro de téléphone au format E.164 (ex: +221771234567)"
    )
    
    class Meta:
        model = Device
        fields = ['id', 'phone_number', 'platform', 'is_active', 'created_at', 'last_used_at']
        read_only_fields = ['id', 'created_at', 'last_used_at']

    def validate_phone_number(self, value):
        """Valide le format E.164 du numéro de téléphone"""
        import re
        if not re.match(r'^\+[1-9]\d{1,14}$', value):
            raise serializers.ValidationError(
                'Le numéro doit être au format E.164 (ex: +221771234567)'
            )
        return value

    def create(self, validated_data):
        user = self.context['request'].user
        # get_or_create pour éviter les doublons et mettre à jour le last_used_at
        device, created = Device.objects.get_or_create(
            user=user, 
            phone_number=validated_data['phone_number'],
            defaults={'platform': validated_data.get('platform', 'android')}
        )
        if not created:
            device.is_active = True # Réactiver si c'était désactivé
            device.save()
        return device
