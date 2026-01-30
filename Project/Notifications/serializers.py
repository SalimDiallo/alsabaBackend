from rest_framework import serializers
from .models import Notification, Device

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'title', 'body', 'notification_type', 'data', 'is_read', 'created_at']
        read_only_fields = ['id', 'title', 'body', 'notification_type', 'data', 'created_at']


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ['fcm_token', 'platform']

    def create(self, validated_data):
        user = self.context['request'].user
        # get_or_create pour éviter les doublons et mettre à jour le last_used_at
        device, created = Device.objects.get_or_create(
            user=user, 
            fcm_token=validated_data['fcm_token'],
            defaults={'platform': validated_data.get('platform', 'android')}
        )
        if not created:
            device.is_active = True # Réactiver si c'était désactivé
            device.save()
        return device
