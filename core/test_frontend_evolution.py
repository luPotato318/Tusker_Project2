"""Rendered-page regressions; run with --settings=piem.test_settings."""
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import School, StudentProject, User, Workshop


class StaticAssetReferenceTests(SimpleTestCase):
    def test_every_literal_template_static_reference_exists(self):
        references = []
        pattern = re.compile(r"{%\s*static\s+(['\"])(.*?)\1\s*%}")
        for template in (settings.BASE_DIR / "core" / "templates").rglob("*.html"):
            for match in pattern.finditer(template.read_text(encoding="utf-8")):
                references.append((template, match.group(2)))
        self.assertTrue(references, "The static reference scan must inspect templates.")
        for template, asset in references:
            with self.subTest(template=template.name, asset=asset):
                self.assertTrue(finders.find(asset), f"Missing static asset: {asset}")

    def test_local_javascript_module_imports_exist(self):
        source_root = settings.BASE_DIR / "core" / "static"
        imports = re.compile(r"(?:from\s+|import\s+)['\"](\.[^'\"]+)['\"]")
        for module in source_root.rglob("*.mjs"):
            for reference in imports.findall(module.read_text(encoding="utf-8")):
                asset = (module.parent / reference).resolve().relative_to(source_root.resolve())
                with self.subTest(module=module.name, asset=asset):
                    self.assertTrue(finders.find(asset.as_posix()))


class PublicPageRenderingTests(TestCase):
    def test_public_pages_render_shared_navigation_and_indexable_metadata(self):
        for route, template in (
            ("home", "core/index.html"),
            ("courses", "core/courses.html"),
            ("showcase", "core/showcase.html"),
        ):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template)
                self.assertContains(response, '<meta name="robots" content="index,follow">', html=True)
                self.assertContains(response, 'id="main-content"')
                self.assertContains(response, 'aria-controls="main-nav"')
                self.assertContains(response, 'aria-current="page"', count=1)
                self.assertContains(response, '<dialog id="version-modal"')
                self.assertRegex(response.content.decode(), r'<meta name="description" content="[^\"]+">')

    def test_authentication_pages_render_without_indexing(self):
        for route in ("login_aluno", "login_admin", "register"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '<meta name="robots" content="noindex,nofollow">', html=True)

    def test_empty_home_shows_actual_zero_counts(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.context["total_alunos"], 0)
        self.assertEqual(response.context["total_projetos"], 0)
        self.assertContains(response, "<strong>0</strong>", count=2, html=True)
        self.assertNotContains(response, "120+")
        self.assertNotContains(response, "45+")
        self.assertNotContains(response, "100%")

    def test_home_updates_community_counts_from_records(self):
        student = User.objects.create_user("student@example.test", nome="Estudante")
        User.objects.create_user("teacher@example.test", nome="Docente", perfil_acesso=User.Role.TEACHER)
        StudentProject.objects.create(aluno=student, titulo="Projeto", area="Educação", resumo="Aprendizado")
        response = self.client.get(reverse("home"))
        self.assertEqual(response.context["total_alunos"], 1)
        self.assertEqual(response.context["total_projetos"], 1)
        self.assertContains(response, "<strong>1</strong>", count=2, html=True)

    def test_catalog_filter_returns_matching_course_and_recoverable_empty_state(self):
        course = Workshop.objects.create(
            titulo="Introdução ao Python", descricao="Aprenda programação na prática",
            area="Tecnologia da Informação", data=timezone.now() + timedelta(days=2),
            modalidade=Workshop.Modality.ONLINE,
        )
        response = self.client.get(reverse("courses"), {"q": "Python", "modalidade": "online"})
        self.assertContains(response, course.titulo)
        self.assertContains(response, "1 curso encontrado")
        self.assertContains(response, '<label for="course-query">O que você quer aprender?</label>', html=True)
        self.assertContains(response, '<label for="course-area">Área de interesse</label>', html=True)
        self.assertContains(response, '<label for="course-modality">Formato</label>', html=True)
        empty = self.client.get(reverse("courses"), {"q": "NoMatchingWorkshop"})
        self.assertContains(empty, "Nenhum curso encontrado")
        self.assertContains(empty, "Ver todos os cursos")
        self.assertNotContains(empty, course.titulo)


class PrivatePageRenderingTests(TestCase):
    def test_role_portals_render_private_metadata(self):
        school = School.objects.create(nome="Escola de teste", codigo="frontend-test")
        for role, route in (
            (User.Role.STUDENT, "dashboard"),
            (User.Role.TEACHER, "teacher_dashboard"),
            (User.Role.RECRUITER, "recruiter_dashboard"),
            (User.Role.ADMIN, "admin_dashboard"),
        ):
            with self.subTest(role=role):
                user = User.objects.create_user(
                    f"{role}@example.test", nome=f"Pessoa {role}",
                    perfil_acesso=role, escola=school,
                )
                self.client.force_login(user)
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '<meta name="robots" content="noindex,nofollow">', html=True)
                self.assertNotContains(response, "piem-speed-insights-config")
