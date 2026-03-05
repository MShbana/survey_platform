from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.surveys.cache import SurveyCacheService


class SurveyCacheServiceTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_key_format(self):
        self.assertEqual(
            SurveyCacheService._make_key(42, "structure"),
            "survey:42:structure",
        )

    def test_get_set_invalidate_roundtrip(self):
        self.assertIsNone(SurveyCacheService.get_structure(1))
        SurveyCacheService.set_structure(1, {"sections": []})
        self.assertEqual(SurveyCacheService.get_structure(1), {"sections": []})
        SurveyCacheService.invalidate_structure(1)
        self.assertIsNone(SurveyCacheService.get_structure(1))

    @override_settings(SURVEY_CACHE_TIMEOUT=999)
    def test_timeout_reads_survey_setting(self):
        self.assertEqual(SurveyCacheService._get_timeout(), 999)

    def test_explicit_timeout_overrides_setting(self):
        self.assertEqual(SurveyCacheService._get_timeout(60), 60)
