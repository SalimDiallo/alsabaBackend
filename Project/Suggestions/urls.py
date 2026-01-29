from django.urls import path
from .views import SuggestionListView, NotificationReadView

urlpatterns = [
    path('', SuggestionListView.as_view(), name='suggestion_list'),
    path('<uuid:id>/read/', NotificationReadView.as_view(), name='notification_read'),
]
