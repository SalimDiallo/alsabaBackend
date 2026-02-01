"""
✅ Redis-Based Throttle Classes for Distributed Rate Limiting

These throttle classes use a dedicated Redis cache ('throttle') to ensure
rate limiting works correctly across multiple Django instances (e.g., Docker containers).

Usage:
    In your view:
        throttle_classes = [RedisUserRateThrottle]
        throttle_scope = 'deposit'
"""

from rest_framework.throttling import SimpleRateThrottle
from django.core.cache import caches
import structlog

logger = structlog.get_logger(__name__)


class RedisThrottleMixin:
    """
    Mixin that overrides the cache to use the dedicated 'throttle' Redis cache.
    This ensures rate limiting is shared across all Django instances.
    """
    
    @property
    def cache(self):
        """Use the dedicated throttle cache instead of default cache."""
        try:
            return caches['throttle']
        except Exception as e:
            # Fallback to default cache if throttle cache is unavailable
            logger.warning("throttle_cache_fallback", error=str(e))
            return caches['default']


class RedisAnonRateThrottle(RedisThrottleMixin, SimpleRateThrottle):
    """
    Rate limiting for anonymous users, using Redis for distributed environments.
    """
    scope = 'anon'

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return None  # Only throttle unauthenticated requests

        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request)
        }


class RedisUserRateThrottle(RedisThrottleMixin, SimpleRateThrottle):
    """
    Rate limiting for authenticated users, using Redis for distributed environments.
    """
    scope = 'user'

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }


class RedisScopedRateThrottle(RedisThrottleMixin, SimpleRateThrottle):
    """
    Rate limiting for specific scopes (e.g., 'deposit', 'withdrawal'),
    using Redis for distributed environments.
    
    Set throttle_scope on your view to define the rate (from DEFAULT_THROTTLE_RATES).
    """
    scope_attr = 'throttle_scope'

    def __init__(self):
        # Override the `scope` attribute to be set dynamically by the view
        pass

    def allow_request(self, request, view):
        # Get the throttle scope from the view
        self.scope = getattr(view, self.scope_attr, None)
        
        if not self.scope:
            return True  # No scope = no throttling

        # Get the rate for this scope
        self.rate = self.get_rate()
        if self.rate is None:
            return True  # No rate configured = no throttling

        self.num_requests, self.duration = self.parse_rate(self.rate)
        self.key = self.get_cache_key(request, view)
        if self.key is None:
            return True

        self.history = self.cache.get(self.key, [])
        self.now = self.timer()

        # Drop any requests from the history which have now passed the throttle duration
        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()
        
        if len(self.history) >= self.num_requests:
            logger.warning(
                "throttle_limit_exceeded",
                scope=self.scope,
                user_id=str(request.user.pk) if request.user.is_authenticated else None,
                ip=self.get_ident(request)
            )
            return self.throttle_failure()
        
        return self.throttle_success()

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }
