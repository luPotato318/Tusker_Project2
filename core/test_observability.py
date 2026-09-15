from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve

from .context_processors import version_context


@override_settings(DEBUG=False, SPEED_INSIGHTS_ENABLED=True, SPEED_INSIGHTS_SAMPLE_RATE=1)
class SpeedInsightsTests(SimpleTestCase):
    def context(self, path):
        request = RequestFactory().get(path)
        request.resolver_match = resolve(request.path)
        request.user = AnonymousUser()
        return version_context(request)

    def test_public_pages_have_one_loader_without_query_data(self):
        for path in ('/', '/cursos/?q=nome%40example.com', '/vitrine/'):
            with self.subTest(path=path):
                context = self.context(path)
                html = render_to_string('core/partials/speed_insights.html', context)
                self.assertEqual(html.count('src="/static/core/js/speed-insights.mjs"'), 1)
                self.assertNotIn('example.com', html)
                self.assertNotIn('?q=', html)
                self.assertEqual(context['PIEM_ROBOTS'], 'index,follow')

    def test_private_and_auth_pages_never_load_telemetry(self):
        for path in ('/entrar/aluno/', '/cadastro/', '/painel/', '/painel/professor/', '/canal-seguro/'):
            with self.subTest(path=path):
                context = self.context(path)
                self.assertIsNone(context['PIEM_SPEED_INSIGHTS'])
                self.assertEqual(context['PIEM_ROBOTS'], 'noindex,nofollow')
                self.assertNotIn('<script', render_to_string('core/partials/speed_insights.html', context))

    @override_settings(DEBUG=True)
    def test_development_does_not_load_telemetry(self):
        self.assertIsNone(self.context('/')['PIEM_SPEED_INSIGHTS'])

    @override_settings(SPEED_INSIGHTS_ENABLED=False)
    def test_configuration_can_disable_telemetry(self):
        self.assertIsNone(self.context('/')['PIEM_SPEED_INSIGHTS'])

    @override_settings(SPEED_INSIGHTS_SAMPLE_RATE=0)
    def test_zero_sampling_does_not_load_script(self):
        self.assertIsNone(self.context('/')['PIEM_SPEED_INSIGHTS'])

    @override_settings(PUBLIC_SITE_URL='https://piem.example')
    def test_social_preview_uses_absolute_static_url(self):
        self.assertEqual(self.context('/')['PIEM_OG_IMAGE'], 'https://piem.example/static/core/og.png')
