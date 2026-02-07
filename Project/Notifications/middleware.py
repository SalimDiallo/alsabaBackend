from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model
import structlog

logger = structlog.get_logger(__name__)
User = get_user_model()

@database_sync_to_async
def get_user_from_token(token_string):
    """
    Récupère l'utilisateur à partir du token JWT de manière sécurisée.
    """
    try:
        # Valider le token
        token = AccessToken(token_string)
        user_id = token.payload.get('user_id')
        
        # Récupérer l'utilisateur en base
        return User.objects.get(id=user_id)
    except Exception as e:
        logger.warning("websocket_jwt_auth_failed", error=str(e))
        return AnonymousUser()

class JWTAuthMiddleware:
    """
    Middleware personnalisé pour authentifier les WebSockets via un token JWT
    passé dans la query string (ex: ws/notifications/?token=...).
    """
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        # Récupérer la query string
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = dict(qp.split("=") for qp in query_string.split("&") if "=" in qp)
        
        token = query_params.get("token")
        
        if token:
            # Authentifier l'utilisateur
            scope['user'] = await get_user_from_token(token)
        else:
            scope['user'] = AnonymousUser()

        return await self.inner(scope, receive, send)

def JWTAuthMiddlewareStack(inner):
    """
    Utilitaire pour envelopper le middleware (similaire à AuthMiddlewareStack).
    """
    return JWTAuthMiddleware(inner)
