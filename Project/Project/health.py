"""
Endpoints de santé pour le monitoring (Docker healthcheck, load balancer, uptime).

- /health/ : liveness. Le process Django répond-il ? Aucune dépendance externe
             touchée, donc jamais de faux négatif qui ferait redémarrer le
             conteneur alors que seul Postgres est en vrac.
- /ready/  : readiness. Les dépendances (DB, Redis, Celery) sont-elles utilisables ?
             Renvoie 503 si l'une est KO, avec le détail par composant.

Ces deux routes sont exclues de l'échantillonnage APM (voir sentry_config.traces_sampler)
pour ne pas polluer le quota de transactions Sentry.
"""
import time

import structlog
from django.core.cache import cache
from django.db import connections
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

logger = structlog.get_logger(__name__)

# Au-delà, la dépendance est considérée dégradée même si elle finit par répondre.
CHECK_TIMEOUT_SECONDS = 5


def _timed(check_name, func):
    """Exécute un check et renvoie (ok, détail) sans jamais lever."""
    started = time.monotonic()
    try:
        func()
    except Exception as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        logger.warning(
            "healthcheck_failed",
            component=check_name,
            error=str(exc),
            latency_ms=elapsed_ms,
        )
        return False, {
            'status': 'error',
            'latency_ms': elapsed_ms,
            # Type seulement : le message peut contenir une URL de connexion
            # avec des identifiants.
            'error': type(exc).__name__,
        }

    elapsed_ms = round((time.monotonic() - started) * 1000, 1)
    status = 'ok' if elapsed_ms <= CHECK_TIMEOUT_SECONDS * 1000 else 'degraded'
    return status == 'ok', {'status': status, 'latency_ms': elapsed_ms}


def _check_database():
    with connections['default'].cursor() as cursor:
        cursor.execute('SELECT 1')
        cursor.fetchone()


def _check_cache():
    key = 'healthcheck:probe'
    cache.set(key, 'ok', 10)
    if cache.get(key) != 'ok':
        raise RuntimeError('cache write/read mismatch')


def _check_celery():
    from Project.celery import app as celery_app

    replies = celery_app.control.ping(timeout=CHECK_TIMEOUT_SECONDS)
    if not replies:
        raise RuntimeError('no celery worker responded to ping')


@csrf_exempt
@never_cache
def liveness(request):
    """Le process répond. Utilisé par le healthcheck Docker du service web."""
    return JsonResponse({'status': 'ok'})


@csrf_exempt
@never_cache
def readiness(request):
    """
    Les dépendances sont utilisables. 200 si tout va bien, 503 sinon.

    Celery est traité comme non bloquant : un worker absent dégrade le service
    (les tâches s'empilent) mais l'API HTTP reste servable, donc il ne fait pas
    basculer le code de retour.
    """
    checks = {}
    db_ok, checks['database'] = _timed('database', _check_database)
    cache_ok, checks['cache'] = _timed('cache', _check_cache)
    _, checks['celery'] = _timed('celery', _check_celery)

    healthy = db_ok and cache_ok
    return JsonResponse(
        {'status': 'ok' if healthy else 'unavailable', 'checks': checks},
        status=200 if healthy else 503,
    )
