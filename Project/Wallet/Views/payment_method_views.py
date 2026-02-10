"""
Views for managing saved payment methods
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
import structlog
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, inline_serializer
from rest_framework import serializers

from ..models import PaymentMethod
from ..Services.payment_method_service import payment_method_service
from ..Serializers.payment_method_serializers import (
    PaymentMethodSerializer,
    CreateCardPaymentMethodSerializer,
    CreateBankAccountPaymentMethodSerializer,
    CreateOrangeMoneyPaymentMethodSerializer,
    UpdatePaymentMethodSerializer
)

logger = structlog.get_logger(__name__)


class PaymentMethodListView(APIView):
    """
    GET /api/wallet/payment-methods/
    Lists the user's saved payment methods
    
    POST /api/wallet/payment-methods/
    Creates a new saved payment method
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="List payment methods",
        description="Retrieves saved payment methods (cards, accounts).",
        tags=['Wallet'],
        operation_id="wallet_payment_methods_list",
        parameters=[
            OpenApiParameter(name='method_type', type=OpenApiTypes.STR, enum=['card', 'bank_account', 'orange_money'], required=False),
            OpenApiParameter(name='active_only', type=OpenApiTypes.BOOL, required=False, default=True),
        ],
        responses={
            200: inline_serializer(
                name='PaymentMethodListResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'payment_methods': PaymentMethodSerializer(many=True),
                    'count': serializers.IntegerField()
                }
            )
        }
    )
    def get(self, request):
        """Lists payment methods"""
        method_type = request.query_params.get('method_type')  # card, bank_account, orange_money
        active_only = request.query_params.get('active_only', 'true').lower() == 'true'
        
        payment_methods = payment_method_service.list_payment_methods(
            user=request.user,
            method_type=method_type,
            active_only=active_only
        )
        
        serializer = PaymentMethodSerializer(payment_methods, many=True)
        
        return Response({
            "success": True,
            "payment_methods": serializer.data,
            "count": len(serializer.data)
        }, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Create a payment method",
        description="Adds a new payment method. 'method_type' determines required fields.",
        request=CreateCardPaymentMethodSerializer, # Simplified for doc, ideally polymorphic
        tags=['Wallet'],
        operation_id="wallet_payment_methods_create",
        responses={
            201: inline_serializer(
                name='PaymentMethodCreateResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'message': serializers.CharField(),
                    'payment_method': PaymentMethodSerializer()
                }
            ),
            400: inline_serializer(
                name='PaymentMethodCreateError',
                fields={
                    'success': serializers.BooleanField(),
                    'error': serializers.CharField(),
                    'code': serializers.CharField(required=False),
                    'details': serializers.JSONField(required=False)
                }
            )
        }
    )
    def post(self, request):
        """Creates a payment method"""
        method_type = request.data.get('method_type')
        
        if method_type == 'card':
            serializer = CreateCardPaymentMethodSerializer(data=request.data)
        elif method_type == 'bank_account':
            serializer = CreateBankAccountPaymentMethodSerializer(data=request.data)
        elif method_type == 'orange_money':
            serializer = CreateOrangeMoneyPaymentMethodSerializer(data=request.data)
        else:
            return Response({
                "success": False,
                "error": "method_type must be 'card', 'bank_account' or 'orange_money'",
                "code": "invalid_method_type"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if not serializer.is_valid():
            return Response({
                "success": False,
                "error": "Invalid data",
                "details": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            if method_type == 'card':
                payment_method = payment_method_service.create_card_payment_method(
                    user=request.user,
                    label=serializer.validated_data['label'],
                    card_number=serializer.validated_data['card_number'],
                    card_expiry_month=str(serializer.validated_data['card_expiry_month']),
                    card_expiry_year=str(serializer.validated_data['card_expiry_year']),
                    card_cvv=serializer.validated_data['card_cvv'],
                    is_default=serializer.validated_data.get('is_default', False)
                )
            elif method_type == 'bank_account':
                payment_method = payment_method_service.create_bank_account_payment_method(
                    user=request.user,
                    label=serializer.validated_data['label'],
                    account_number=serializer.validated_data['account_number'],
                    bank_code=serializer.validated_data['bank_code'],
                    account_name=serializer.validated_data['account_name'],
                    bank_name=serializer.validated_data.get('bank_name'),
                    bank_country=serializer.validated_data.get('bank_country'),
                    is_default=serializer.validated_data.get('is_default', False)
                )
            elif method_type == 'orange_money':
                payment_method = payment_method_service.create_orange_money_payment_method(
                    user=request.user,
                    label=serializer.validated_data['label'],
                    orange_money_number=serializer.validated_data['orange_money_number'],
                    is_default=serializer.validated_data.get('is_default', False)
                )
            
            result_serializer = PaymentMethodSerializer(payment_method)
            
            logger.info(
                "payment_method_created",
                user_id=str(request.user.id),
                method_id=str(payment_method.id),
                method_type=method_type
            )
            
            return Response({
                "success": True,
                "message": "Payment method created successfully",
                "payment_method": result_serializer.data
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error("payment_method_creation_failed", error=str(e), user_id=str(request.user.id))
            return Response({
                "success": False,
                "error": f"Error during creation: {str(e)}",
                "code": "creation_failed"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PaymentMethodDetailView(APIView):
    """
    GET /api/wallet/payment-methods/{id}/
    Retrieves a payment method
    
    PATCH /api/wallet/payment-methods/{id}/
    Updates a payment method
    
    DELETE /api/wallet/payment-methods/{id}/
    Disables a payment method
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Payment method detail",
        tags=['Wallet'],
        operation_id="wallet_payment_methods_retrieve",
        responses={
            200: inline_serializer(
                name='PaymentMethodDetailResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'payment_method': PaymentMethodSerializer()
                }
            ),
            404: {"description": "Not found"}
        }
    )
    def get(self, request, payment_method_id):
        """Retrieves a payment method"""
        try:
            payment_method = payment_method_service.get_payment_method(
                request.user, payment_method_id
            )
            serializer = PaymentMethodSerializer(payment_method)
            
            return Response({
                "success": True,
                "payment_method": serializer.data
            }, status=status.HTTP_200_OK)
            
        except PaymentMethod.DoesNotExist:
            return Response({
                "success": False,
                "error": "Payment method not found",
                "code": "payment_method_not_found"
            }, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({
                "success": False,
                "error": str(e),
                "code": "invalid_payment_method"
            }, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Update a payment method",
        description="Updates the label or default status.",
        request=UpdatePaymentMethodSerializer,
        tags=['Wallet'],
        operation_id="wallet_payment_methods_update",
        responses={
            200: inline_serializer(
                name='PaymentMethodUpdateResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'message': serializers.CharField(),
                    'payment_method': PaymentMethodSerializer()
                }
            ),
            400: {"description": "Invalid data"},
            404: {"description": "Not found"}
        }
    )
    def patch(self, request, payment_method_id):
        """Updates a payment method"""
        try:
            payment_method = payment_method_service.get_payment_method(
                request.user, payment_method_id
            )
            
            serializer = UpdatePaymentMethodSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({
                    "success": False,
                    "error": "Invalid data",
                    "details": serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
            
            validated_data = serializer.validated_data
            
            # Field updates
            if 'label' in validated_data:
                payment_method.label = validated_data['label']
            if 'is_default' in validated_data:
                # If setting as default, disable others
                if validated_data['is_default']:
                    PaymentMethod.objects.filter(
                        user=request.user,
                        method_type=payment_method.method_type,
                        is_default=True
                    ).exclude(id=payment_method.id).update(is_default=False)
                payment_method.is_default = validated_data['is_default']
            if 'is_active' in validated_data:
                payment_method.is_active = validated_data['is_active']
            
            payment_method.save()
            
            result_serializer = PaymentMethodSerializer(payment_method)
            
            logger.info(
                "payment_method_updated",
                user_id=str(request.user.id),
                method_id=str(payment_method.id)
            )
            
            return Response({
                "success": True,
                "message": "Payment method updated successfully",
                "payment_method": result_serializer.data
            }, status=status.HTTP_200_OK)
            
        except PaymentMethod.DoesNotExist:
            return Response({
                "success": False,
                "error": "Payment method not found",
                "code": "payment_method_not_found"
            }, status=status.HTTP_404_NOT_FOUND)

    @extend_schema(
        summary="Delete a payment method",
        description="Disables (soft delete) a payment method. It will no longer be offered for payments.",
        tags=['Wallet'],
        operation_id="wallet_payment_methods_destroy",
        responses={
            200: inline_serializer(
                name='PaymentMethodDeleteResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'message': serializers.CharField()
                }
            )
        }
    )
    def delete(self, request, payment_method_id):
        """Disables a payment method (soft delete)"""
        try:
            payment_method = payment_method_service.get_payment_method(
                request.user, payment_method_id
            )
            
            payment_method.is_active = False
            payment_method.is_default = False
            payment_method.save()
            
            logger.info(
                "payment_method_deleted",
                user_id=str(request.user.id),
                method_id=str(payment_method.id)
            )
            
            return Response({
                "success": True,
                "message": "Payment method disabled successfully"
            }, status=status.HTTP_200_OK)
            
        except PaymentMethod.DoesNotExist:
            return Response({
                "success": False,
                "error": "Payment method not found",
                "code": "payment_method_not_found"
            }, status=status.HTTP_404_NOT_FOUND)


class PaymentMethodSetDefaultView(APIView):
    """
    POST /api/wallet/payment-methods/{id}/set-default/
    Sets a payment method as default
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Set as default",
        description="Sets this payment method as the default for its type.",
        tags=['Wallet'],
        responses={
            200: inline_serializer(
                name='PaymentMethodSetDefaultResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'message': serializers.CharField(),
                    'payment_method': PaymentMethodSerializer()
                }
            )
        },
        request=None
    )
    def post(self, request, payment_method_id):
        """Sets a method as default"""
        try:
            payment_method = payment_method_service.get_payment_method(
                request.user, payment_method_id
            )
            
            # Disable other default methods of the same type
            PaymentMethod.objects.filter(
                user=request.user,
                method_type=payment_method.method_type,
                is_default=True
            ).exclude(id=payment_method.id).update(is_default=False)
            
            # Set this one as default
            payment_method.is_default = True
            payment_method.save()
            
            logger.info(
                "payment_method_set_default",
                user_id=str(request.user.id),
                method_id=str(payment_method.id)
            )
            
            return Response({
                "success": True,
                "message": "Payment method set as default",
                "payment_method": PaymentMethodSerializer(payment_method).data
            }, status=status.HTTP_200_OK)
            
        except PaymentMethod.DoesNotExist:
            return Response({
                "success": False,
                "error": "Payment method not found",
                "code": "payment_method_not_found"
            }, status=status.HTTP_404_NOT_FOUND)
