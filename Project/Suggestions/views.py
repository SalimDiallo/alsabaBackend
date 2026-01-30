from rest_framework import generics, permissions, status, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from Notifications.models import Notification

class SuggestionSerializer(serializers.ModelSerializer):
    offer_id = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ['id', 'title', 'body', 'score', 'is_read', 'created_at', 'offer_id', 'data']

    def get_offer_id(self, obj):
        return obj.data.get('offer_id')

    def get_score(self, obj):
        return obj.data.get('score', 0)

class SuggestionListView(generics.ListAPIView):
    """
    GET /api/suggestions/
    Flux "Pour Vous" basé sur le type 'suggestion'.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SuggestionSerializer

    def get_queryset(self):
        return Notification.objects.filter(
            user=self.request.user, 
            notification_type='suggestion'
        ).order_by('-created_at')

class NotificationReadView(APIView):
    """
    POST /api/suggestions/{id}/read/
    Marquer comme lu (centralisé).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        notif = get_object_or_404(Notification, id=id, user=request.user)
        notif.is_read = True
        notif.save()
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)
