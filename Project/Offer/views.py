from rest_framework import status, permissions, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404

from .models import Offer, Dispute
from .serializers import (
    OfferSerializer, CreateOfferSerializer, AcceptOfferSerializer,
    DisputeOfferSerializer, UpdateOfferSerializer, ValidateOfferSerializer,
    DisputeSerializer, InitiateDisputeSerializer, ResolveDisputeSerializer
)
from .services import SecureEscrowService
from Project.idempotency import idempotent_endpoint
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
import structlog

logger = structlog.get_logger(__name__)

class OfferListView(generics.ListAPIView):
    """
    GET /api/offers/
    Liste les offres visibles (OPEN ou les miennes).
    """
    serializer_class = OfferSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Lister les offres P2P",
        description="Liste les offres disponibles (OPEN) ou celles impliquant l'utilisateur connecté.",
        tags=['Offres P2P'],
        responses={200: OfferSerializer(many=True)}
    )
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
    throttle_scope = 'offer_create'

    @extend_schema(
        summary="Créer une offre P2P",
        description="Crée une nouvelle offre de swap de devises. L'utilisateur doit avoir un solde suffisant dans la devise de vente.",
        request=CreateOfferSerializer,
        tags=['Offres P2P'],
        responses={
            201: OfferSerializer,
            400: {"description": "Solde insuffisant ou données invalides"},
            429: {"description": "Limite de création atteinte"}
        }
    )
    @idempotent_endpoint()
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

    @extend_schema(
        summary="Modifier une offre P2P",
        description="Permet de modifier une offre existante si elle est encore ouverte (OPEN) et appartient à l'utilisateur.",
        request=UpdateOfferSerializer,
        tags=['Offres P2P'],
        responses={200: OfferSerializer, 403: {"description": "Non autorisé"}}
    )
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

    @extend_schema(
        summary="Détail d'une offre P2P",
        description="Récupère les informations complètes d'une offre spécifique.",
        tags=['Offres P2P'],
        responses={200: OfferSerializer, 404: {"description": "Offre introuvable"}}
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

class AcceptOfferView(APIView):
    """
    POST /api/offers/{id}/accept/
    Accepter une offre.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'offer_accept'

    @extend_schema(
        summary="Accepter une offre P2P",
        description="Permet à un second utilisateur d'accepter une offre ouverte. L'accepteur doit fournir les détails de son bénéficiaire (celui qui recevra les fonds).",
        request=AcceptOfferSerializer,
        tags=['Offres P2P'],
        responses={
            200: OfferSerializer,
            400: {"description": "Offre non disponible ou déjà acceptée"},
            403: {"description": "L'auteur ne peut pas accepter sa propre offre"}
        }
    )
    @idempotent_endpoint()
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

    @extend_schema(
        summary="Valider une offre (Vendeur)",
        description="Le créateur de l'offre (Vendeur) valide l'acceptation et fournit les détails du bénéficiaire qui recevra les fondus de l'accepteur.",
        request=ValidateOfferSerializer,
        tags=['Offres P2P'],
        responses={200: OfferSerializer, 400: {"description": "Action non autorisée à ce stade"}}
    )
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

    @extend_schema(
        summary="Confirmer la transaction P2P",
        description="Valide et exécute techniquement le swap (transfert des fonds entre les wallets et libération de l'escrow) une fois toutes les conditions réunies.",
        tags=['Offres P2P'],
        responses={200: OfferSerializer, 400: {"description": "Conditions de swap non remplies"}},
        request=None
    )
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

class BeneficiaryConfirmView(APIView):
    """
    POST /api/offers/{id}/beneficiary-confirm/
    Confirmation par un bénéficiaire (B1 ou B2).
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Confirmation bénéficiaire P2P",
        description="Permet à l'un des bénéficiaires impliqués dans le swap de confirmer manuellement la réception des fonds hors-plateforme si nécessaire.",
        tags=['Offres P2P'],
        responses={200: OfferSerializer},
        request=None
    )
    def post(self, request, id):
        try:
            offer = SecureEscrowService.confirm_beneficiary_participation(
                user=request.user,
                offer_id=id
            )
            return Response(OfferSerializer(offer).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("beneficiary_confirm_failed", offer_id=str(id), user_id=str(request.user.id))
            return Response({'error': "Erreur lors de la confirmation bénéficiaire"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CancelOfferView(APIView):
    """
    POST /api/offers/{id}/cancel/
    Annuler une offre.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Annuler une offre P2P",
        description="Annule une offre existante. Si l'offre était en cours de traitement, les fonds en escrow sont restitués.",
        tags=['Offres P2P'],
        responses={200: OfferSerializer, 400: {"description": "Annulation impossible à ce stade"}},
        request=None
    )
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

    @extend_schema(
        summary="Ouvrir un litige",
        description="Ouvre un litige formel sur une offre en cours de transaction. Bloque l'exécution jusqu'à résolution par un admin.",
        request=DisputeOfferSerializer,
        tags=['Offres P2P'],
        responses={200: OfferSerializer, 400: {"description": "Litige impossible"}}
    )
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

# ✅ NOUVEAU: Endpoints pour la gestion des litiges
class InitiateDisputeView(APIView):
    """
    POST /api/offers/{offer_id}/disputes/
    Initier un litige sur une offre.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="Initier un litige",
        description="Crée un nouveau litige associé à un offre spécifique. Bloque le swap si celui-ci n'a pas été confirmé.",
        request=InitiateDisputeSerializer,
        tags=['Offres P2P'],
        responses={201: DisputeSerializer, 400: {"description": "Litige déjà existant ou offre terminée"}}
    )
    def post(self, request, offer_id):
        serializer = InitiateDisputeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            dispute = SecureEscrowService.initiate_dispute(
                offer_id=offer_id,
                user_initiator=request.user,
                reason=serializer.validated_data['reason'],
                evidence=serializer.validated_data.get('evidence', {})
            )
            return Response(
                DisputeSerializer(dispute).data,
                status=status.HTTP_201_CREATED
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Offer.DoesNotExist:
            return Response({'error': 'Offre non trouvée'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception("initiate_dispute_failed", offer_id=offer_id)
            return Response(
                {'error': 'Erreur lors de la création du litige'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DisputeDetailView(APIView):
    """
    GET /api/disputes/{dispute_id}/
    Récupérer les détails d'un litige.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="Détail d'un litige",
        description="Récupère les détails d'un litige spécifique (raisons, preuves, statut).",
        tags=['Offres P2P'],
        responses={200: DisputeSerializer, 403: {"description": "Non autorisé"}, 404: {"description": "Introuvable"}}
    )
    def get(self, request, dispute_id):
        dispute = get_object_or_404(Dispute, id=dispute_id)
        
        # Vérifier l'accès: partie de l'offre ou admin
        if (dispute.offer.user != request.user and
            dispute.offer.accepted_by != request.user and
            not request.user.is_staff):
            return Response(
                {'error': 'Non autorisé'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return Response(DisputeSerializer(dispute).data, status=status.HTTP_200_OK)


class ListDisputesView(generics.ListAPIView):
    """
    GET /api/disputes/
    Lister les litiges (pour l'utilisateur ou pour les admins).
    """
    serializer_class = DisputeSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="Lister les litiges",
        description="Liste tous les litiges accessibles à l'utilisateur connecté (ses propres litiges ou tous pour les admins).",
        tags=['Offres P2P'],
        responses={200: DisputeSerializer(many=True)}
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        user = self.request.user
        
        # Admin voit tous les litiges
        if user.is_staff:
            return Dispute.objects.all().select_related(
                'offer', 'initiated_by', 'reviewed_by'
            ).order_by('-created_at')
        
        # User voit seulement ses litiges (initiés ou concernant ses offres)
        return Dispute.objects.filter(
            Q(initiated_by_id=user.id) |
            Q(offer__user_id=user.id) |
            Q(offer__accepted_by_id=user.id)
        ).select_related('offer', 'initiated_by', 'reviewed_by').order_by('-created_at')


class ResolveDisputeView(APIView):
    """
    POST /api/disputes/{dispute_id}/resolve/
    Résoudre un litige (Admin only).
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="Résoudre un litige (Admin)",
        description="Permet à un administrateur de trancher un litige, soit par annulation du swap, soit par exécution forcée.",
        request=ResolveDisputeSerializer,
        tags=['Offres P2P'],
        responses={200: DisputeSerializer, 403: {"description": "Action réservée aux admins"}}
    )
    def post(self, request, dispute_id):
        if not request.user.is_staff:
            return Response(
                {'error': 'Seul un administrateur peut résoudre les litiges'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = ResolveDisputeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            dispute = SecureEscrowService.review_dispute(
                dispute_id=dispute_id,
                reviewer=request.user,
                resolution=serializer.validated_data['resolution'],
                notes=serializer.validated_data.get('notes')
            )
            return Response(DisputeSerializer(dispute).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Dispute.DoesNotExist:
            return Response({'error': 'Litige non trouvé'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception("resolve_dispute_failed", dispute_id=dispute_id)
            return Response(
                {'error': 'Erreur lors de la résolution'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )