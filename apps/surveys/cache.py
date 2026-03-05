"""Survey-specific cache service.

Wraps :class:`~apps.common.cache.CacheService` with convenience methods for
the survey structure cache (key pattern ``survey:{id}:structure``).
"""

from django.conf import settings

from apps.common.cache import CacheService


class SurveyCacheService(CacheService):
    """Cache service for survey structure data.

    Uses the ``SURVEY_CACHE_TIMEOUT`` setting for the default timeout.
    """

    key_prefix = "survey"

    @classmethod
    def _get_timeout(cls, timeout=None):
        """Resolve timeout, preferring ``SURVEY_CACHE_TIMEOUT`` setting.

        Priority: explicit argument > ``SURVEY_CACHE_TIMEOUT`` setting >
        base class resolution chain.
        """
        if timeout is not None:
            return timeout
        survey_timeout = getattr(settings, "SURVEY_CACHE_TIMEOUT", None)
        if survey_timeout is not None:
            return survey_timeout
        return super()._get_timeout(timeout)

    @classmethod
    def get_structure(cls, survey_id):
        """Get cached survey structure.

        Args:
            survey_id: Primary key of the survey.

        Returns:
            The cached structure data, or ``None``.
        """
        return cls.get(survey_id, suffix="structure")

    @classmethod
    def set_structure(cls, survey_id, data):
        """Cache survey structure data.

        Args:
            survey_id: Primary key of the survey.
            data: Serialized survey structure to cache.
        """
        cls.set(survey_id, data, suffix="structure")

    @classmethod
    def invalidate_structure(cls, survey_id):
        """Invalidate cached survey structure.

        Args:
            survey_id: Primary key of the survey.
        """
        cls.invalidate(survey_id, suffix="structure")
