from importlib.resources import path
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import NotificationViewSet, DeviceViewSet

router = DefaultRouter()
router.register(r'', NotificationViewSet, basename='notifications')
# router.register(r'devices', DeviceViewSet, basename='devices') # On va faire une route custom pour device car create only

urlpatterns = [
    path('register-device/', DeviceViewSet.as_view({'post': 'create'}), name='register-device'),
    path('', include(router.urls)),
]
