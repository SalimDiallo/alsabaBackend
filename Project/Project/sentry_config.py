"""
Configuration avancée de Sentry pour ALSABA
Gère le monitoring, APM, et les alertes
"""
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.redis import RedisIntegration
import structlog
import logging
from sentry_sdk.integrations.logging import LoggingIntegration

logger = structlog.get_logger(__name__)


def before_send(event, hint):
    """
    Hook exécuté avant l'envoi d'un événement à Sentry.
    Permet de filtrer les données sensibles et d'enrichir le contexte.
    """
    # Filtrer les données sensibles
    if 'request' in event:
        request_data = event.get('request', {})
        
        # Supprimer les headers sensibles
        if 'headers' in request_data:
            sensitive_headers = ['Authorization', 'X-Api-Key', 'Cookie']
            for header in sensitive_headers:
                request_data['headers'].pop(header, None)
        
        # Supprimer les données sensibles du body
        if 'data' in request_data:
            sensitive_fields = ['password', 'cvv', 'card_number', 'api_key', 'secret']
            for field in sensitive_fields:
                if isinstance(request_data['data'], dict):
                    request_data['data'].pop(field, None)
    
    # Filtrer les exceptions non critiques
    if 'exception' in event:
        exceptions = event.get('exception', {}).get('values', [])
        for exc in exceptions:
            exc_type = exc.get('type', '')
            # Ignorer les 404 et autres erreurs non critiques
            if exc_type in ['Http404', 'NotFound', 'PermissionDenied']:
                return None
    
    return event


def before_send_transaction(event, hint):
    """
    Hook pour les transactions APM.
    Permet d'enrichir les transactions avec des tags personnalisés.
    """
    # Ajouter des tags personnalisés selon le type de transaction
    if 'transaction' in event:
        transaction_name = event['transaction']
        
        # Identifier les transactions financières critiques
        if any(keyword in transaction_name.lower() for keyword in ['deposit', 'withdrawal', 'transfer', 'payment']):
            event['tags'] = event.get('tags', {})
            event['tags']['critical'] = 'true'
            event['tags']['category'] = 'financial'
        
        # Identifier les transactions P2P
        if 'offer' in transaction_name.lower() or 'escrow' in transaction_name.lower():
            event['tags'] = event.get('tags', {})
            event['tags']['category'] = 'p2p'
        
        # Identifier les transactions KYC
        if 'kyc' in transaction_name.lower() or 'didit' in transaction_name.lower():
            event['tags'] = event.get('tags', {})
            event['tags']['category'] = 'kyc'
    
    return event


def traces_sampler(sampling_context):
    """
    Détermine le taux d'échantillonnage pour chaque transaction.
    Permet de capturer 100% des transactions critiques et 10% des autres.
    """
    # Contexte de la transaction
    asgi_scope = sampling_context.get("asgi_scope") or sampling_context.get("wsgi_environ") or {}
    path = asgi_scope.get("path") or asgi_scope.get("PATH_INFO") or ""
    transaction_name = sampling_context.get("transaction_context", {}).get("name", "")

    # Ignorer les sondes de santé : elles sont appelées en continu par Docker
    # et le load balancer, et brûleraient le quota de transactions pour rien.
    noise_paths = ('/health/', '/ready/', '/ping/')
    if path in noise_paths or transaction_name in noise_paths:
        return 0.0

    if path:
        # 100% pour les endpoints critiques
        critical_paths = [
            '/api/wallet/deposit/',
            '/api/wallet/withdrawal/',
            '/api/offers/accept/',
            '/api/offers/validate/',
            '/api/offers/confirm/',
            '/api/accounts/kyc/',
        ]
        
        if any(critical_path in path for critical_path in critical_paths):
            return 1.0  # 100%
        
        # 50% pour les webhooks
        if '/webhook/' in path:
            return 0.5
        
    # Par défaut : 10% (y compris les tâches Celery, qui n'ont pas de path)
    return 0.1


def configure_sentry(dsn, environment, release=None, debug=False):
    """
    Configure Sentry avec APM et intégrations.
    
    Args:
        dsn (str): Sentry DSN
        environment (str): Environnement (development, staging, production)
        release (str): Version de l'application
        debug (bool): Mode debug
    """
    if not dsn:
        logger.warning("sentry_dsn_missing", message="Sentry DSN non configuré")
        return
    
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        
        # Intégrations
        integrations=[
            DjangoIntegration(
                transaction_style='url',  # Utiliser l'URL comme nom de transaction
                middleware_spans=True,    # Tracer les middlewares
                signals_spans=True,       # Tracer les signaux Django
            ),
            CeleryIntegration(
                monitor_beat_tasks=True,  # Monitorer les tâches Celery Beat
                propagate_traces=True,    # Propager les traces entre Django et Celery
            ),
            RedisIntegration(),
            LoggingIntegration(
                level=logging.INFO,        # Logs INFO envoyés comme breadcrumbs
                event_level=logging.ERROR  # Logs ERROR capturés comme événements
            ),
        ],
        
        # APM (Application Performance Monitoring)
        traces_sampler=traces_sampler,  # Échantillonnage intelligent
        
        # Profiling (optionnel, consomme plus de ressources)
        profiles_sample_rate=0.1 if not debug else 0,  # 10% en production, 0% en debug
        
        # Hooks
        before_send=before_send,
        before_send_transaction=before_send_transaction,
        
        # Options de confidentialité
        send_default_pii=False,  # Ne pas envoyer les PII par défaut
        
        # Gestion des erreurs
        attach_stacktrace=True,  # Attacher la stack trace
        max_breadcrumbs=50,      # Nombre max de breadcrumbs
        
        # Performance
        max_request_body_size='medium',  # Taille max du body (10KB)
        
        # Ignorer certaines erreurs
        ignore_errors=[
            'rest_framework.exceptions.NotFound',
            'rest_framework.exceptions.PermissionDenied',
            'django.http.Http404',
        ],
        
        # Debug
        debug=debug,
    )
    
    logger.info(
        "sentry_configured",
        environment=environment,
        apm_enabled=True,
        profiling_enabled=(not debug)
    )


def add_transaction_context(transaction_type, user_id=None, currency=None, amount=None, **extra):
    """
    Ajoute du contexte personnalisé à la transaction Sentry en cours.
    
    Args:
        transaction_type (str): Type de transaction (deposit, withdrawal, p2p, etc.)
        user_id (str): ID de l'utilisateur
        currency (str): Devise
        amount (float): Montant
        **extra: Contexte additionnel
    """
    # Scope d'isolation : le contexte reste attaché à la requête / tâche Celery
    # en cours, et non au span courant qui peut se fermer avant l'erreur.
    scope = sentry_sdk.get_isolation_scope()

    # Tags
    scope.set_tag("transaction_type", transaction_type)
    if currency:
        scope.set_tag("currency", currency)

    # Contexte utilisateur (sans PII)
    if user_id:
        scope.set_user({"id": str(user_id)})

    # Contexte personnalisé
    scope.set_context("transaction", {
        "type": transaction_type,
        "currency": currency,
        "amount": amount,
        **extra
    })


def capture_financial_error(error, transaction_type, user_id=None, amount=None, currency=None, **extra):
    """
    Capture une erreur financière critique avec contexte enrichi.
    
    Args:
        error (Exception): L'exception à capturer
        transaction_type (str): Type de transaction
        user_id (str): ID utilisateur
        amount (float): Montant
        currency (str): Devise
        **extra: Contexte additionnel
    """
    with sentry_sdk.new_scope() as scope:
        # Tags critiques
        scope.set_tag("critical", "true")
        scope.set_tag("category", "financial")
        scope.set_tag("transaction_type", transaction_type)
        
        if currency:
            scope.set_tag("currency", currency)
        
        # Contexte
        scope.set_context("financial_transaction", {
            "type": transaction_type,
            "user_id": str(user_id) if user_id else None,
            "amount": amount,
            "currency": currency,
            **extra
        })
        
        # Niveau de sévérité
        scope.level = "error"
        
        # Capturer l'erreur
        sentry_sdk.capture_exception(error)
        
        logger.error(
            "financial_error_captured",
            error=str(error),
            transaction_type=transaction_type,
            user_id=str(user_id) if user_id else None
        )
