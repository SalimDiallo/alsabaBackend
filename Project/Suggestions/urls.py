from django.urls import path
from .views import SuggestionListView, NotificationReadView, RecommendationFeedView

urlpatterns = [
    path('', SuggestionListView.as_view(), name='suggestion_list'),
    # Flux "Pour Vous" temps réel (classement des offres OPEN)
    path('feed/', RecommendationFeedView.as_view(), name='recommendation_feed'),
    path('<uuid:id>/read/', NotificationReadView.as_view(), name='notification_read'),
]
