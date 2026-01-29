"""
Vues pour gérer les méthodes de paiement sauvegardées
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
import structlog

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
    Liste les méthodes de paiement sauvegardées de l'utilisateur
    
    POST /api/wallet/payment-methods/
    Crée une nouvelle méthode de paiement sauvegardée
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Liste les méthodes de paiement"""
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

    def post(self, request):
        """Crée une méthode de paiement"""
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
                "error": "method_type doit être 'card', 'bank_account' ou 'orange_money'",
                "code": "invalid_method_type"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if not serializer.is_valid():
            return Response({
                "success": False,
                "error": "Données invalides",
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
                "message": "Méthode de paiement créée avec succès",
                "payment_method": result_serializer.data
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error("payment_method_creation_failed", error=str(e), user_id=str(request.user.id))
            return Response({
                "success": False,
                "error": f"Erreur lors de la création: {str(e)}",
                "code": "creation_failed"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PaymentMethodDetailView(APIView):
    """
    GET /api/wallet/payment-methods/{id}/
    Récupère une méthode de paiement
    
    PATCH /api/wallet/payment-methods/{id}/
    Met à jour une méthode de paiement
    
    DELETE /api/wallet/payment-methods/{id}/
    Désactive une méthode de paiement
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, payment_method_id):
        """Récupère une méthode de paiement"""
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
                "error": "Méthode de paiement non trouvée",
                "code": "payment_method_not_found"
            }, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({
                "success": False,
                "error": str(e),
                "code": "invalid_payment_method"
            }, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, payment_method_id):
        """Met à jour une méthode de paiement"""
        try:
            payment_method = payment_method_service.get_payment_method(
                request.user, payment_method_id
            )
            
            serializer = UpdatePaymentMethodSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({
                    "success": False,
                    "error": "Données invalides",
                    "details": serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
            
            validated_data = serializer.validated_data
            
            # Mise à jour des champs
            if 'label' in validated_data:
                payment_method.label = validated_data['label']
            if 'is_default' in validated_data:
                # Si on définit comme défaut, désactiver les autres
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
                "message": "Méthode de paiement mise à jour avec succès",
                "payment_method": result_serializer.data
            }, status=status.HTTP_200_OK)
            
        except PaymentMethod.DoesNotExist:
            return Response({
                "success": False,
                "error": "Méthode de paiement non trouvée",
                "code": "payment_method_not_found"
            }, status=status.HTTP_404_NOT_FOUND)

    def delete(self, request, payment_method_id):
        """Désactive une méthode de paiement (soft delete)"""
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
                "message": "Méthode de paiement désactivée avec succès"
            }, status=status.HTTP_200_OK)
            
        except PaymentMethod.DoesNotExist:
            return Response({
                "success": False,
                "error": "Méthode de paiement non trouvée",
                "code": "payment_method_not_found"
            }, status=status.HTTP_404_NOT_FOUND)


class PaymentMethodSetDefaultView(APIView):
    """
    POST /api/wallet/payment-methods/{id}/set-default/
    Définit une méthode de paiement comme méthode par défaut
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, payment_method_id):
        """Définit une méthode comme défaut"""
        try:
            payment_method = payment_method_service.get_payment_method(
                request.user, payment_method_id
            )
            
            # Désactiver les autres méthodes par défaut du même type
            PaymentMethod.objects.filter(
                user=request.user,
                method_type=payment_method.method_type,
                is_default=True
            ).exclude(id=payment_method.id).update(is_default=False)
            
            # Définir celle-ci comme défaut
            payment_method.is_default = True
            payment_method.save()
            
            logger.info(
                "payment_method_set_default",
                user_id=str(request.user.id),
                method_id=str(payment_method.id)
            )
            
            return Response({
                "success": True,
                "message": "Méthode de paiement définie comme méthode par défaut",
                "payment_method": PaymentMethodSerializer(payment_method).data
            }, status=status.HTTP_200_OK)
            
        except PaymentMethod.DoesNotExist:
            return Response({
                "success": False,
                "error": "Méthode de paiement non trouvée",
                "code": "payment_method_not_found"
            }, status=status.HTTP_404_NOT_FOUND)
