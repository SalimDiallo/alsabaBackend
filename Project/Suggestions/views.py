from rest_framework import generics, permissions, status, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.utils import timezone
from Notifications.models import Notification
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, extend_schema_field

class SuggestionSerializer(serializers.ModelSerializer):
    offer_id = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ['id', 'title', 'body', 'score', 'is_read', 'created_at', 'offer_id', 'data']

    @extend_schema_field(OpenApiTypes.STR)
    def get_offer_id(self, obj):
        return obj.data.get('offer_id')

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_score(self, obj):
        return obj.data.get('score', 0)

class SuggestionListView(generics.ListAPIView):
    """
    GET /api/suggestions/
    Flux "Pour Vous" basé sur le type 'suggestion'.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SuggestionSerializer

    @extend_schema(
        summary="Lister les suggestions",
        description="Obtenir le flux de suggestions personnalisées (matchs potentiels) pour l'utilisateur connecté.",
        tags=['Suggestions'],
        responses={200: SuggestionSerializer(many=True)}
    )
    def get_queryset(self):
        return Notification.objects.filter(
            user=self.request.user, 
            notification_type='suggestion'
        ).order_by('-created_at')

class NotificationReadView(APIView):
    """
    POST /api/suggestions/{id}/read/
    Marquer comme lu (centralisé).
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Marquer comme lu",
        description="Marque une suggestion spécifique comme lue.",
        tags=['Suggestions'],
        responses={200: {"description": "OK"}},
        request=None
    )
    def post(self, request, id):
        notif = get_object_or_404(Notification, id=id, user=request.user)
        notif.is_read = True
        notif.save()
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)


class RecommendationFeedView(APIView):
    """
    GET /api/suggestions/feed/
    Flux "Pour Vous" TEMPS RÉEL : classe les offres OPEN actuellement disponibles
    pour l'utilisateur, avec score + explication (breakdown, raisons).
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Flux de recommandations 'Pour Vous'",
        description=(
            "Classe en temps réel les offres OPEN pertinentes pour l'utilisateur "
            "(compatibilité devise, faisabilité, compétitivité du taux, affinité "
            "corridor, réputation, fraîcheur). Chaque résultat inclut un score et "
            "son explication."
        ),
        tags=['Suggestions'],
        parameters=[
            OpenApiParameter(name='limit', type=OpenApiTypes.INT, required=False,
                             description="Nombre max de résultats (défaut 20, max 50)"),
            OpenApiParameter(name='include_unaffordable', type=OpenApiTypes.BOOL, required=False,
                             description="Inclure les offres non finançables (défaut true)"),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        from django.conf import settings
        from Offer.models import Offer
        from Offer.serializers import OfferSerializer
        from Wallet.models import Wallet
        from .recommendation_engine import RecommendationEngine

        limit = min(int(request.query_params.get('limit', 20) or 20), 50)
        include_unaffordable = str(
            request.query_params.get('include_unaffordable', 'true')
        ).lower() in ('true', '1', 'yes')

        wallet = Wallet.objects.filter(user=request.user).first()
        if not wallet:
            return Response({"success": True, "count": 0, "results": [],
                             "message": "Aucun wallet — impossible de recommander."},
                            status=status.HTTP_200_OK)

        # Présélection performante : offres OPEN, dans la devise que l'utilisateur
        # peut engager (currency_buy = devise wallet), non expirées, hors les siennes.
        candidates = (
            Offer.objects.filter(
                status='OPEN',
                currency_buy=wallet.currency,
                expires_at__gt=timezone.now(),
            )
            .exclude(user=request.user)
            .select_related('user')
            .order_by('-created_at')[: getattr(settings, 'RECOMMENDATION_FEED_CANDIDATES', 200)]
        )

        scored = RecommendationEngine.rank_offers_for_user(
            request.user, candidates, limit=limit,
            include_unaffordable=include_unaffordable,
        )

        results = []
        for so in scored:
            item = OfferSerializer(so.offer).data
            item['recommendation'] = so.to_dict()
            results.append(item)

        return Response({
            "success": True,
            "count": len(results),
            "results": results,
        }, status=status.HTTP_200_OK)
