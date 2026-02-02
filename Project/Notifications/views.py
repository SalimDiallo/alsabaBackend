from rest_framework import viewsets, mixins, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from .models import Notification
from .serializers import NotificationSerializer, DeviceSerializer
from drf_spectacular.utils import extend_schema

class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Liste les notifications de l'utilisateur connecté.
    Permet de marquer comme lu.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    @extend_schema(
        summary="Lister les notifications",
        description="Récupère la liste des notifications de l'utilisateur.",
        tags=['Notifications'],
        responses={200: NotificationSerializer(many=True)}
    )
    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @extend_schema(summary="Marquer une notification comme lue", description="Marque une notification spécifique comme lue.", tags=['Notifications'], responses={200: {"description": "Succès"}})
    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        """Mark notification as read"""
        notification = self.get_object()
        notification.is_read = True
        notification.save()
        return Response({'status': 'marked as read'})

    @extend_schema(summary="Tout marquer comme lu", description="Marque toutes les notifications de l'utilisateur comme lues.", tags=['Notifications'], responses={200: {"description": "Succès"}})
    @action(detail=False, methods=['post'])
    def read_all(self, request):
        """Mark all notifications as read"""
        self.get_queryset().update(is_read=True)
        return Response({'status': 'all marked as read'})


class DeviceViewSet(viewsets.GenericViewSet):
    """
    Endpoint pour enregistrer le token FCM du mobile.
    POST /api/notifications/devices/
    """
    permission_classes = [IsAuthenticated]
    serializer_class = DeviceSerializer

    @extend_schema(
        summary="Enregistrer un appareil (FCM)",
        description="Enregistre un token FCM pour recevoir les notifications push.",
        request=DeviceSerializer,
        tags=['Notifications'],
        responses={201: {"description": "Appareil enregistré"}}
    )
    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"status": "Device registered"}, status=status.HTTP_201_CREATED)
