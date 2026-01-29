from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import Offer
from .serializers import OfferSerializer, CreateOfferSerializer, AcceptOfferSerializer, DisputeOfferSerializer
from .services import SecureEscrowService
import structlog

logger = structlog.get_logger(__name__)

class OfferViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet pour visualiser et interagir avec les offres.
    Lecture seule par défaut, actions spécifiques pour créer/accepter.
    """
    serializer_class = OfferSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Retourne les offres visibles :
        1. Offres OPEN (Marché)
        2. Mes offres (quel que soit le statut)
        3. Offres que j'ai acceptées
        """
        user = self.request.user
        return Offer.objects.filter(
            Q(status='OPEN') | 
            Q(user=user) | 
            Q(accepted_by=user)
        ).select_related('user', 'accepted_by').order_by('-created_at')

    @action(detail=False, methods=['post'], url_path='create')
    def create_offer(self, request):
        serializer = CreateOfferSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            try:
                # Constuction beneficiary_data
                beneficiary_data = {}
                if 'beneficiary_name' in data:
                    beneficiary_data['name'] = data['beneficiary_name']
                if 'beneficiary_phone' in data:
                    beneficiary_data['phone'] = data['beneficiary_phone']

                offer = SecureEscrowService.create_offer(
                    user=request.user,
                    amount_sell=data['amount_sell'],
                    currency_sell=data['currency_sell'],
                    amount_buy=data['amount_buy'],
                    currency_buy=data['currency_buy'],
                    beneficiary_data=beneficiary_data,
                    expiry_hours=data['expiry_hours']
                )
                return Response(OfferSerializer(offer).data, status=status.HTTP_201_CREATED)
            
            except ValidationError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.exception("create_offer_failed", user_id=str(request.user.id))
                return Response({'error': "Une erreur est survenue"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='accept')
    def accept_offer(self, request, pk=None):
        """
        Accepter une offre (A2 accepte l'offre de A1).
        Verrouille les fonds (Escrow).
        """
        serializer = AcceptOfferSerializer(data=request.data)
        if serializer.is_valid():
            try:
                # Construction beneficiary_data pour B1
                beneficiary_data = {}
                data = serializer.validated_data
                if 'beneficiary_name' in data:
                    beneficiary_data['name'] = data['beneficiary_name']
                if 'beneficiary_phone' in data:
                    beneficiary_data['phone'] = data['beneficiary_phone']

                offer = SecureEscrowService.accept_offer(
                    user_accepter=request.user,
                    offer_id=pk,
                    beneficiary_data=beneficiary_data
                )
                return Response(OfferSerializer(offer).data, status=status.HTTP_200_OK)

            except ValidationError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.exception("accept_offer_failed", offer_id=str(pk), user_id=str(request.user.id))
                return Response({'error': "Erreur lors de l'acceptation"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel_offer(self, request, pk=None):
        """
        Annuler une offre (Seulement par le créateur ou admin).
        """
        offer = self.get_object()
        if offer.user != request.user and not request.user.is_staff:
             return Response({'error': "Non autorisé"}, status=status.HTTP_403_FORBIDDEN)
             
        try:
            SecureEscrowService.cancel_transaction(offer.id, reason="Cancelled by user")
            # Re-fetch pour le statut mis à jour
            offer.refresh_from_db()
            return Response(OfferSerializer(offer).data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='confirm')
    def confirm_offer(self, request, pk=None):
        """
        Confirmer/Exécuter l'échange (Phase finale).
        Débloque les fonds et effectue les transferts.
        """
        try:
            # Pour l'instant, n'importe quelle partie peut déclencher la confirmation (selon implémentation service)
            # Idéalement, c'est une confirmation mutuelle process.
            SecureEscrowService.confirm_transaction(offer_id=pk)
            
            offer = self.get_object() # Refresh
            return Response(OfferSerializer(offer).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("confirm_offer_failed", offer_id=str(pk))
            return Response({'error': "Erreur lors de la confirmation"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='dispute')
    def dispute_offer(self, request, pk=None):
        """
        Ouvrir un litige sur une offre.
        """
        serializer = DisputeOfferSerializer(data=request.data)
        if serializer.is_valid():
            try:
                offer = SecureEscrowService.dispute_transaction(
                    offer_id=pk,
                    user=request.user,
                    reason=serializer.validated_data['reason']
                )
                return Response(OfferSerializer(offer).data, status=status.HTTP_200_OK)
            except ValidationError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.exception("dispute_offer_failed", offer_id=str(pk))
                return Response({'error': "Erreur interne"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
