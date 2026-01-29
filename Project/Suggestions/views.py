from rest_framework import generics, permissions, status, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from .models import Notification

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'title', 'message', 'score', 'is_read', 'created_at', 'offer']

class SuggestionListView(generics.ListAPIView):
    """
    GET /api/suggestions/
    Flux "Pour Vous".
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(
            user=self.request.user, 
            type='SUGGESTION'
        ).order_by('-score', '-created_at')

class NotificationReadView(APIView):
    """
    POST /api/suggestions/{id}/read/
    Marquer comme lu.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        notif = get_object_or_404(Notification, id=id, user=request.user)
        notif.is_read = True
        notif.save()
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)
