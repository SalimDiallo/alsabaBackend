from functools import wraps
from django.core.cache import caches
from rest_framework.response import Response
from rest_framework import status
import structlog

logger = structlog.get_logger(__name__)

def idempotent_endpoint(cache_name='default', timeout=86400, required=False):
    """
    Decorator to ensure idempotency for an API endpoint.
    Uses 'Idempotency-Key' header to cache responses.

    Args:
        cache_name (str): The Django cache alias to use (default: 'default').
        timeout (int): Expiration time in seconds (default: 24h).
        required (bool): If True, reject requests without an Idempotency-Key
            header (400). À activer sur les opérations financières critiques
            (dépôt, retrait, création/acceptation d'offre) pour empêcher les
            doubles soumissions.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(view_instance, request, *args, **kwargs):
            # 1. Check for Idempotency-Key header
            idempotency_key = request.headers.get('Idempotency-Key')
            if not idempotency_key:
                if required:
                    logger.warning(
                        "idempotency_key_missing_on_required_endpoint",
                        path=request.path,
                        user_id=str(request.user.id) if request.user.is_authenticated else 'anon'
                    )
                    return Response(
                        {
                            "success": False,
                            "error": "Idempotency-Key header requis pour cette opération",
                            "code": "idempotency_key_required"
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
                # Optionnel : on procède normalement.
                return view_func(view_instance, request, *args, **kwargs)

            # 2. Scope the key to the user (security)
            user_id = str(request.user.id) if request.user.is_authenticated else 'anon'
            
            # 3. Create a unique cache key
            # user_id + key allows different users to coincidentally use same key 'uuid-v4'
            cache_key = f"idempotency:{user_id}:{idempotency_key}"
            
            cache = caches[cache_name]
            
            # 4. Check if we already have a response stored
            stored_response = cache.get(cache_key)
            if stored_response:
                logger.info("idempotency_hit", user_id=user_id, key=idempotency_key)
                
                # Check stored status to handle 'processing' vs 'completed'
                if stored_response.get('status') == 'processing':
                    # Concurrent request with same key! 
                    return Response(
                        {"error": "Request with this Idempotency-Key is currently processing"},
                        status=status.HTTP_409_CONFLICT
                    )
                
                # Resend the stored finished response
                return Response(
                    stored_response['data'],
                    status=stored_response['status_code']
                )

            # 5. Mark key as 'processing' to prevent concurrent race conditions
            # Set a short expiry for processing state (e.g. 60s) in case crash
            cache.set(cache_key, {'status': 'processing'}, timeout=60)

            try:
                # 6. Process the actual view
                response = view_func(view_instance, request, *args, **kwargs)
                
                # 7. Only cache successful responses (200, 201)
                # We usually don't want to idempotently return 500s or 400s forever 
                # (user might want to retry with fixed payload but same key?)
                # Standard practice: Cache 2xx/3xx. 4xx depends on logic.
                if status.is_success(response.status_code):
                    # We need to render the response data if it's not already rendered
                    if hasattr(response, 'render') and callable(response.render):
                        response.render()
                        
                    response_data = {
                        'status': 'completed',
                        'status_code': response.status_code,
                        'data': response.data
                    }
                    cache.set(cache_key, response_data, timeout=timeout)
                else:
                    # If failed, delete the key so user can retry
                     cache.delete(cache_key)

                return response

            except Exception as e:
                # If application crashes, remove key so user can retry
                cache.delete(cache_key)
                raise e

        return _wrapped_view
    return decorator
