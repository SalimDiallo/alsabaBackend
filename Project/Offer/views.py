from rest_framework import status, permissions, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404

from .models import Offer
from .serializers import OfferSerializer, CreateOfferSerializer, AcceptOfferSerializer, DisputeOfferSerializer, UpdateOfferSerializer, ValidateOfferSerializer
from .services import SecureEscrowService
import structlog

logger = structlog.get_logger(__name__)

class OfferListView(generics.ListAPIView):
    """
    GET /api/offers/
    Liste les offres visibles (OPEN ou les miennes).
    """
    serializer_class = OfferSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return Offer.objects.filter(
            Q(status='OPEN') | 
            Q(user=user) | 
            Q(accepted_by=user)
        ).select_related('user', 'accepted_by').order_by('-created_at')

class CreateOfferView(APIView):
    """
    POST /api/offers/create/
    Créer une nouvelle offre.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = CreateOfferSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            try:
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

class UpdateOfferView(APIView):
    """
    PUT /api/offers/{id}/update/
    Modifier une offre existante (Seulement si OPEN et Owner).
    """
    permission_classes = [permissions.IsAuthenticated]

    def put(self, request, id):
        offer = get_object_or_404(Offer, id=id)
        if offer.user != request.user:
            return Response({'error': "Non autorisé"}, status=status.HTTP_403_FORBIDDEN)
        
        if offer.status != 'OPEN':
             return Response({'error': "Impossible de modifier une offre en cours de traitement"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = UpdateOfferSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            try:
                # Mise à jour des champs
                if 'amount_sell' in data:
                    offer.amount_sell_cents = int(data['amount_sell'] * 100)
                if 'currency_sell' in data:
                    offer.currency_sell = data['currency_sell']
                if 'amount_buy' in data:
                    offer.amount_buy_cents = int(data['amount_buy'] * 100)
                if 'currency_buy' in data:
                    offer.currency_buy = data['currency_buy']
                
                # Recalcul du taux si montants changés
                if 'amount_sell' in data or 'amount_buy' in data:
                    offer.rate = Decimal(offer.amount_buy_cents) / Decimal(offer.amount_sell_cents)

                offer.save()
                return Response(OfferSerializer(offer).data, status=status.HTTP_200_OK)
            except Exception as e:
                logger.exception("update_offer_failed", offer_id=str(id))
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class OfferDetailView(generics.RetrieveAPIView):
    """
    GET /api/offers/{id}/
    Détail d'une offre.
    """
    serializer_class = OfferSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Offer.objects.all()
    lookup_field = 'id'

class AcceptOfferView(APIView):
    """
    POST /api/offers/{id}/accept/
    Accepter une offre.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        serializer = AcceptOfferSerializer(data=request.data)
        if serializer.is_valid():
            try:
                beneficiary_data = {}
                data = serializer.validated_data
                if 'beneficiary_name' in data:
                    beneficiary_data['name'] = data['beneficiary_name']
                if 'beneficiary_phone' in data:
                    beneficiary_data['phone'] = data['beneficiary_phone']

                offer = SecureEscrowService.accept_offer(
                    user_accepter=request.user,
                    offer_id=id,
                    beneficiary_data=beneficiary_data
                )
                return Response(OfferSerializer(offer).data, status=status.HTTP_200_OK)

            except ValidationError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.exception("accept_offer_failed", offer_id=str(id), user_id=str(request.user.id))
                return Response({'error': "Erreur lors de l'acceptation"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ValidateOfferView(APIView):
    """
    POST /api/offers/{id}/validate/
    A1 valide et ajoute son bénéficiaire (B2).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        serializer = ValidateOfferSerializer(data=request.data)
        if serializer.is_valid():
            try:
                beneficiary_data = {}
                data = serializer.validated_data
                if 'beneficiary_name' in data:
                    beneficiary_data['name'] = data['beneficiary_name']
                if 'beneficiary_phone' in data:
                    beneficiary_data['phone'] = data['beneficiary_phone']

                offer = SecureEscrowService.validate_offer(
                    user_validator=request.user,
                    offer_id=id,
                    beneficiary_data=beneficiary_data
                )
                return Response(OfferSerializer(offer).data, status=status.HTTP_200_OK)

            except ValidationError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.exception("validate_offer_failed", offer_id=str(id), user_id=str(request.user.id))
                return Response({'error': "Erreur lors de la validation"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ConfirmOfferView(APIView):
    """
    POST /api/offers/{id}/confirm/
    Valider et exécuter le swap.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        try:
            SecureEscrowService.confirm_transaction(offer_id=id)
            offer = get_object_or_404(Offer, id=id)
            return Response(OfferSerializer(offer).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("confirm_offer_failed", offer_id=str(id))
            return Response({'error': "Erreur lors de la confirmation"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CancelOfferView(APIView):
    """
    POST /api/offers/{id}/cancel/
    Annuler une offre.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        offer = get_object_or_404(Offer, id=id)
        if offer.user != request.user and not request.user.is_staff:
             return Response({'error': "Non autorisé"}, status=status.HTTP_403_FORBIDDEN)
             
        try:
            SecureEscrowService.cancel_transaction(offer.id, reason="Cancelled by user")
            offer.refresh_from_db()
            return Response(OfferSerializer(offer).data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class DisputeOfferView(APIView):
    """
    POST /api/offers/{id}/dispute/
    Ouvrir un litige.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        serializer = DisputeOfferSerializer(data=request.data)
        if serializer.is_valid():
            try:
                offer = SecureEscrowService.dispute_transaction(
                    offer_id=id,
                    user=request.user,
                    reason=serializer.validated_data['reason']
                )
                return Response(OfferSerializer(offer).data, status=status.HTTP_200_OK)
            except ValidationError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.exception("dispute_offer_failed", offer_id=str(id))
                return Response({'error': "Erreur interne"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
