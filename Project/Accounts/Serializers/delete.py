from rest_framework import serializers
class AccountDeleteSerializer(serializers.Serializer):
    """Demande de suppression"""
    reason = serializers.CharField(max_length=100, required=False, allow_blank=True)

class AccountDeleteConfirmSerializer(serializers.Serializer):
    """Confirmation avec OTP"""
    code = serializers.CharField(min_length=6, max_length=6)
    session_key = serializers.CharField(required=True)  # session créée lors de la demande