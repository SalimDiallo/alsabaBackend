from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OfferViewSet

router = DefaultRouter()
router.register(r'', OfferViewSet, basename='offer')

urlpatterns = [
    path('', include(router.urls)),
]
