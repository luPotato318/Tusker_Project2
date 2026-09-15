from unittest.mock import patch

from django.contrib.staticfiles import finders
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from .media_engine import get_contextual_image


@override_settings(STATIC_URL="/static/")
class MediaEngineEvolutionTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.env = patch.dict("core.media_engine.os.environ", {"UNSPLASH_ACCESS_KEY": "", "PEXELS_API_KEY": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(cache.clear)

    @patch("core.media_engine._get_json")
    def test_without_credentials_uses_bundled_image_without_network(self, get_json):
        result = get_contextual_image("Tecnologia da Informação")
        self.assertEqual(result, "/static/core/images/learning-path.svg")
        self.assertIsNotNone(finders.find("core/images/learning-path.svg"))
        get_json.assert_not_called()

    @patch.dict("core.media_engine.os.environ", {"UNSPLASH_ACCESS_KEY": "configured"})
    @patch("core.media_engine._get_json")
    def test_provider_success_is_cached(self, get_json):
        get_json.return_value = {"results": [{"urls": {"regular": "https://images.unsplash.com/example"}}]}
        self.assertEqual(get_contextual_image("liderança"), "https://images.unsplash.com/example")
        self.assertEqual(get_contextual_image("liderança"), "https://images.unsplash.com/example")
        get_json.assert_called_once()

    @patch.dict("core.media_engine.os.environ", {"UNSPLASH_ACCESS_KEY": "configured", "PEXELS_API_KEY": "configured"})
    @patch("core.media_engine._get_json")
    def test_pexels_recovers_from_invalid_unsplash_payload(self, get_json):
        get_json.side_effect = [
            {"results": None},
            {"photos": [{"src": {"large2x": "https://images.pexels.com/example.jpg"}}]},
        ]
        self.assertEqual(get_contextual_image("tecnologia"), "https://images.pexels.com/example.jpg")
        self.assertEqual(get_json.call_count, 2)

    @patch.dict("core.media_engine.os.environ", {"UNSPLASH_ACCESS_KEY": "configured", "PEXELS_API_KEY": "configured"})
    @patch("core.media_engine._get_json", side_effect=OSError("provider unavailable"))
    def test_provider_outage_uses_local_fallback(self, get_json):
        self.assertEqual(get_contextual_image("oratória"), "/static/core/images/learning-path.svg")
        self.assertEqual(get_json.call_count, 2)

    @patch.dict("core.media_engine.os.environ", {"UNSPLASH_ACCESS_KEY": "configured"})
    @patch("core.media_engine._get_json")
    def test_non_https_and_non_string_urls_fall_back_safely(self, get_json):
        for index, url in enumerate(["javascript:alert(1)", "http://example.com/image", None, {"url": "invalid"}]):
            get_json.return_value = {"results": [{"urls": {"regular": url}}]}
            self.assertEqual(get_contextual_image(f"query {index}"), "/static/core/images/learning-path.svg")

    @patch("core.media_engine.cache.set")
    def test_long_queries_produce_bounded_cache_keys(self, cache_set):
        get_contextual_image("consulta " * 100)
        self.assertLess(len(cache_set.call_args.args[0]), 100)
