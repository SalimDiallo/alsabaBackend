from django.urls import path
from .views import (
    OfferListView, 
    CreateOfferView, 
    OfferDetailView,
    UpdateOfferView,
    AcceptOfferView,
    ValidateOfferView, 
    ConfirmOfferView, 
    CancelOfferView, 
    DisputeOfferView,
    InitiateDisputeView,
    DisputeDetailView,
    ListDisputesView,
    ResolveDisputeView
)

urlpatterns = [
    # Lister et Créer
    path('', OfferListView.as_view(), name='offer_list'),
    path('create/', CreateOfferView.as_view(), name='create_offer'),
    
    # Détail
    path('<uuid:id>/', OfferDetailView.as_view(), name='offer_detail'),
    path('<uuid:id>/update/', UpdateOfferView.as_view(), name='update_offer'),
    
    # Actions
    path('<uuid:id>/accept/', AcceptOfferView.as_view(), name='accept_offer'),
    path('<uuid:id>/validate/', ValidateOfferView.as_view(), name='validate_offer'),
    path('<uuid:id>/confirm/', ConfirmOfferView.as_view(), name='confirm_offer'),
    path('<uuid:id>/cancel/', CancelOfferView.as_view(), name='cancel_offer'),
    path('<uuid:id>/dispute/', DisputeOfferView.as_view(), name='dispute_offer'),
    
    # ✅ NOUVEAU: Endpoints pour les litiges
    path('<uuid:offer_id>/disputes/', InitiateDisputeView.as_view(), name='initiate_dispute'),
    path('disputes/', ListDisputesView.as_view(), name='list_disputes'),
    path('disputes/<uuid:dispute_id>/', DisputeDetailView.as_view(), name='dispute_detail'),
    path('disputes/<uuid:dispute_id>/resolve/', ResolveDisputeView.as_view(), name='resolve_dispute'),
]