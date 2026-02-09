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
from .exchange_service import ExchangeRateService
from Project.idempotency import idempotent_endpoint
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
import structlog

logger = structlog.get_logger(__name__)

class OfferListView(generics.ListAPIView):
    """
    GET /api/offers/
    Lists visible offers (OPEN or mine).
    """
    serializer_class = OfferSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="List P2P offers",
        description="Lists available offers (OPEN) or those involving the connected user.",
        tags=['P2P Offers'],
        responses={200: OfferSerializer(many=True)}
    )
    def get_queryset(self):
        user = self.request.user
        return Offer.objects.filter(
            Q(status='OPEN') | 
            Q(user=user) | 
            Q(accepted_by=user)
        ).select_related('user', 'accepted_by').order_by('-created_at')

class ForeignOfferListView(generics.ListAPIView):
    """
    GET /api/offers/foreign/
    Lists OPEN offers that do not come from the user's country.
    Optional filters: currency_sell, currency_buy, min_amount, max_amount.
    """
    serializer_class = OfferSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="List foreign offers",
        description="Lists OPEN offers excluding those created by users from the same country as the connected user.",
        tags=['P2P Offers'],
        parameters=[
            OpenApiParameter(name='currency_sell', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description="Currency sold by the creator"),
            OpenApiParameter(name='currency_buy', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description="Currency the creator wants to receive"),
            OpenApiParameter(name='min_amount', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description="Minimum amount (in currency_sell units)"),
            OpenApiParameter(name='max_amount', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description="Maximum amount (in currency_sell units)"),
        ],
        responses={200: OfferSerializer(many=True)}
    )
    def get_queryset(self):
        user = self.request.user
        # Exclude offers from the user's country
        queryset = Offer.objects.filter(status='OPEN').exclude(user__country_code=user.country_code)

        # Additional Filters
        cs = self.request.query_params.get('currency_sell')
        cb = self.request.query_params.get('currency_buy')
        min_amt = self.request.query_params.get('min_amount')
        max_amt = self.request.query_params.get('max_amount')

        if cs:
            queryset = queryset.filter(currency_sell=cs.upper())
        if cb:
            queryset = queryset.filter(currency_buy=cb.upper())
        if min_amt:
            try:
                min_cents = int(float(min_amt) * 100)
                queryset = queryset.filter(amount_sell_cents__gte=min_cents)
            except ValueError:
                pass
        if max_amt:
            try:
                max_cents = int(float(max_amt) * 100)
                queryset = queryset.filter(amount_sell_cents__lte=max_cents)
            except ValueError:
                pass

        return queryset.select_related('user', 'accepted_by').order_by('-created_at')

class CreateOfferView(APIView):
    """
    POST /api/offers/create/
    Create a new offer.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'offer_create'

    @extend_schema(
        summary="Create a P2P offer",
        description="Creates a new currency swap offer. The user must have a sufficient balance in the selling currency.",
        request=CreateOfferSerializer,
        tags=['P2P Offers'],
        responses={
            201: OfferSerializer,
            400: {"description": "Insufficient balance or invalid data"},
            429: {"description": "Creation limit reached"}
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
                return Response({'error': "An error occurred"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UpdateOfferView(APIView):
    """
    PUT /api/offers/{id}/update/
    Modify an existing offer (Only if OPEN and Owner).
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Modify a P2P offer",
        description="Allows modifying an existing offer if it is still open (OPEN) and belongs to the user.",
        request=UpdateOfferSerializer,
        tags=['P2P Offers'],
        responses={200: OfferSerializer, 403: {"description": "Unauthorized"}}
    )
    def put(self, request, id):
        offer = get_object_or_404(Offer, id=id)
        if offer.user != request.user:
            return Response({'error': "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
        
        if offer.status != 'OPEN':
             return Response({'error': "Cannot modify an offer currently being processed"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = UpdateOfferSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            try:
                # Field updates
                if 'amount_sell' in data:
                    offer.amount_sell_cents = int(data['amount_sell'] * 100)
                if 'currency_sell' in data:
                    offer.currency_sell = data['currency_sell']
                if 'amount_buy' in data:
                    offer.amount_buy_cents = int(data['amount_buy'] * 100)
                if 'currency_buy' in data:
                    offer.currency_buy = data['currency_buy']
                
                # Recalculate rate if amounts changed
                if 'amount_sell' in data or 'amount_buy' in data:
                    from decimal import Decimal
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
    Offer detail.
    """
    serializer_class = OfferSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Offer.objects.all()
    lookup_field = 'id'

    @extend_schema(
        summary="P2P offer detail",
        description="Retrieves the full information of a specific offer.",
        tags=['P2P Offers'],
        responses={200: OfferSerializer, 404: {"description": "Offer not found"}}
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

class AcceptOfferView(APIView):
    """
    POST /api/offers/{id}/accept/
    Accept an offer.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'offer_accept'

    @extend_schema(
        summary="Accept a P2P offer",
        description="Allows a second user to accept an open offer. The accepter must provide their beneficiary details (who will receive the funds).",
        request=AcceptOfferSerializer,
        tags=['P2P Offers'],
        responses={
            200: OfferSerializer,
            400: {"description": "Offer not available or already accepted"},
            403: {"description": "The author cannot accept their own offer"}
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
                return Response({'error': "Error during acceptance"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ValidateOfferView(APIView):
    """
    POST /api/offers/{id}/validate/
    A1 validates and adds their beneficiary (B2).
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Validate an offer (Seller)",
        description="The offer creator (Seller) validates the acceptance and provides details of the beneficiary who will receive the funds from the accepter.",
        request=ValidateOfferSerializer,
        tags=['P2P Offers'],
        responses={200: OfferSerializer, 400: {"description": "Action not authorized at this stage"}}
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
                return Response({'error': "Error during validation"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ConfirmOfferView(APIView):
    """
    POST /api/offers/{id}/confirm/
    Validate and execute the swap.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Confirm P2P transaction",
        description="Validates and technically executes the swap (transfer of funds between wallets and release of escrow) once all conditions are met.",
        tags=['P2P Offers'],
        responses={200: OfferSerializer, 400: {"description": "Swap conditions not met"}},
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
            return Response({'error': "Error during confirmation"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class BeneficiaryConfirmView(APIView):
    """
    POST /api/offers/{id}/beneficiary-confirm/
    Confirmation by a beneficiary (B1 or B2).
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="P2P beneficiary confirmation",
        description="Allows one of the beneficiaries involved in the swap to manually confirm the receipt of funds off-platform if necessary.",
        tags=['P2P Offers'],
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
            return Response({'error': "Error during beneficiary confirmation"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CancelOfferView(APIView):
    """
    POST /api/offers/{id}/cancel/
    Cancel an offer.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Cancel a P2P offer",
        description="Cancels an existing offer. If the offer was being processed, the escrowed funds are returned.",
        tags=['P2P Offers'],
        responses={200: OfferSerializer, 400: {"description": "Cancellation impossible at this stage"}},
        request=None
    )
    def post(self, request, id):
        offer = get_object_or_404(Offer, id=id)
        if offer.user != request.user and not request.user.is_staff:
             return Response({'error': "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
             
        try:
            SecureEscrowService.cancel_transaction(offer.id, reason="Cancelled by user")
            offer.refresh_from_db()
            return Response(OfferSerializer(offer).data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class DisputeOfferView(APIView):
    """
    POST /api/offers/{id}/dispute/
    Open a dispute.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Open a dispute",
        description="Opens a formal dispute on an offer in transaction. Blocks execution until resolution by an admin.",
        request=DisputeOfferSerializer,
        tags=['P2P Offers'],
        responses={200: OfferSerializer, 400: {"description": "Dispute impossible"}}
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
                return Response({'error': "Internal error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# Endpoints for dispute management
class InitiateDisputeView(APIView):
    """
    POST /api/offers/{offer_id}/disputes/
    Initiate a dispute on an offer.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="Initiate a dispute",
        description="Creates a new dispute associated with a specific offer. Blocks the swap if it hasn't been confirmed.",
        request=InitiateDisputeSerializer,
        tags=['P2P Offers'],
        responses={201: DisputeSerializer, 400: {"description": "Dispute already exists or offer completed"}}
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
            return Response({'error': 'Offer not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception("initiate_dispute_failed", offer_id=offer_id)
            return Response(
                {'error': 'Error during dispute creation'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DisputeDetailView(APIView):
    """
    GET /api/disputes/{dispute_id}/
    Retrieve dispute details.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="Dispute details",
        description="Retrieves the details of a specific dispute (reasons, evidence, status).",
        tags=['P2P Offers'],
        responses={200: DisputeSerializer, 403: {"description": "Unauthorized"}, 404: {"description": "Not found"}}
    )
    def get(self, request, dispute_id):
        dispute = get_object_or_404(Dispute, id=dispute_id)
        
        # Check access: part of the offer or admin
        if (dispute.offer.user != request.user and
            dispute.offer.accepted_by != request.user and
            not request.user.is_staff):
            return Response(
                {'error': 'Unauthorized'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return Response(DisputeSerializer(dispute).data, status=status.HTTP_200_OK)


class ListDisputesView(generics.ListAPIView):
    """
    GET /api/disputes/
    List disputes (for user or for admins).
    """
    serializer_class = DisputeSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="List disputes",
        description="Lists all disputes accessible to the connected user (their own disputes or all for admins).",
        tags=['P2P Offers'],
        responses={200: DisputeSerializer(many=True)}
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        user = self.request.user
        
        # Admin sees all disputes
        if user.is_staff:
            return Dispute.objects.all().select_related(
                'offer', 'initiated_by', 'reviewed_by'
            ).order_by('-created_at')
        
        # User only sees their own disputes (initiated or concerning their offers)
        return Dispute.objects.filter(
            Q(initiated_by_id=user.id) |
            Q(offer__user_id=user.id) |
            Q(offer__accepted_by_id=user.id)
        ).select_related('offer', 'initiated_by', 'reviewed_by').order_by('-created_at')


class ResolveDisputeView(APIView):
    """
    POST /api/disputes/{dispute_id}/resolve/
    Resolve a dispute (Admin only).
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="Resolve a dispute (Admin)",
        description="Allows an administrator to decide a dispute, either by cancelling the swap or by forced execution.",
        request=ResolveDisputeSerializer,
        tags=['P2P Offers'],
        responses={200: DisputeSerializer, 403: {"description": "Action reserved for admins"}}
    )
    def post(self, request, dispute_id):
        if not request.user.is_staff:
            return Response(
                {'error': 'Only an administrator can resolve disputes'},
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
            return Response({'error': 'Dispute not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception("resolve_dispute_failed", dispute_id=dispute_id)
            return Response(
                {'error': 'Error during resolution'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class ExchangeRateView(APIView):
    """
    GET /api/offers/exchange-rates/
    Retrieves official exchange rates for a given currency.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get official exchange rates",
        description="Retrieves current exchange rates from ExchangeRate-API (with Redis caching). Useful for guiding the user when creating an offer.",
        tags=['P2P Offers'],
        parameters=[
            OpenApiParameter(name='base', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description="Base currency (ex: EUR, XOF, NGN). Default: EUR")
        ],
        responses={200: OpenApiTypes.OBJECT}
    )
    def get(self, request):
        base_currency = request.query_params.get('base', 'EUR').upper()
        rates = ExchangeRateService.get_rates(base_currency)
        
        if rates:
            return Response({
                "base": base_currency,
                "rates": rates,
                "provider": "ExchangeRate-API",
                "cached": True
            }, status=status.HTTP_200_OK)
        
        return Response({
            "error": "Unable to retrieve rates at the moment."
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)