"""Generic cache service base class.

Provides a reusable cache-aside pattern with key generation, timeout
resolution, and debug logging.  Subclasses set ``key_prefix`` and
optionally ``default_timeout`` to create domain-specific cache services.

Usage::

    class ProductCacheService(CacheService):
        key_prefix = "product"
        default_timeout = 300

    ProductCacheService.set(42, {"name": "Widget"}, suffix="detail")
    ProductCacheService.get(42, suffix="detail")
"""

import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class CacheService:
    """Base class for domain-specific cache services.

    All methods are classmethods — no instantiation needed, matching the
    project's service-layer convention.

    Class attributes:
        key_prefix (str): Required. Prefix for all cache keys.
        default_timeout (int | None): Optional. Falls back to
            ``settings.DEFAULT_CACHE_TIMEOUT``, then Django's default.
    """

    key_prefix: str = ""
    default_timeout: int | None = None

    @classmethod
    def _make_key(cls, object_id, suffix=""):
        """Build a cache key from prefix, object ID, and optional suffix.

        Args:
            object_id: Identifier for the cached object.
            suffix: Optional key suffix (e.g., ``"structure"``).

        Returns:
            str: Cache key like ``"survey:42:structure"`` or ``"survey:42"``.
        """
        if suffix:
            return f"{cls.key_prefix}:{object_id}:{suffix}"
        return f"{cls.key_prefix}:{object_id}"

    @classmethod
    def _get_timeout(cls, timeout=None):
        """Resolve the cache timeout to use.

        Priority: explicit argument > class attribute > settings attribute
        > Django default (``None``).

        Args:
            timeout: Explicit timeout in seconds, or ``None``.

        Returns:
            int | None: Resolved timeout.
        """
        if timeout is not None:
            return timeout
        if cls.default_timeout is not None:
            return cls.default_timeout
        return getattr(settings, "DEFAULT_CACHE_TIMEOUT", None)

    @classmethod
    def get(cls, object_id, suffix=""):
        """Retrieve a value from the cache.

        Args:
            object_id: Identifier for the cached object.
            suffix: Optional key suffix.

        Returns:
            The cached value, or ``None`` on a miss.
        """
        key = cls._make_key(object_id, suffix)
        value = cache.get(key)
        if value is not None:
            logger.debug("Cache hit: %s", key)
        else:
            logger.debug("Cache miss: %s", key)
        return value

    @classmethod
    def set(cls, object_id, value, suffix="", timeout=None):
        """Store a value in the cache.

        Args:
            object_id: Identifier for the cached object.
            value: The value to cache.
            suffix: Optional key suffix.
            timeout: Explicit timeout in seconds, or ``None`` to use
                the resolved default.
        """
        key = cls._make_key(object_id, suffix)
        cache.set(key, value, cls._get_timeout(timeout))
        logger.debug("Cache set: %s", key)

    @classmethod
    def invalidate(cls, object_id, suffix=""):
        """Delete a value from the cache.

        Args:
            object_id: Identifier for the cached object.
            suffix: Optional key suffix.
        """
        key = cls._make_key(object_id, suffix)
        cache.delete(key)
        logger.debug("Cache invalidated: %s", key)

    @classmethod
    def get_or_set(cls, object_id, default_func, suffix="", timeout=None):
        """Cache-aside: return cached value or compute, cache, and return.

        Args:
            object_id: Identifier for the cached object.
            default_func: Zero-argument callable invoked on cache miss.
            suffix: Optional key suffix.
            timeout: Explicit timeout in seconds, or ``None``.

        Returns:
            The cached or freshly-computed value.
        """
        value = cls.get(object_id, suffix)
        if value is not None:
            return value
        value = default_func()
        cls.set(object_id, value, suffix, timeout)
        return value
