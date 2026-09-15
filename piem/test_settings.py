"""Offline tests: never load developer credentials or connect to a live database."""
import os

os.environ["PIEM_READ_DOT_ENV"] = "false"
os.environ["SECRET_KEY"] = "piem-isolated-test-secret-not-for-production-0123456789"
os.environ["DEBUG"] = "false"
os.environ["USE_POSTGRES"] = "false"
os.environ["REDIS_URL"] = ""
os.environ["SPEED_INSIGHTS_ENABLED"] = "false"
os.environ["SPEED_INSIGHTS_SAMPLE_RATE"] = "1"
os.environ["SAFE_REPORT_ENCRYPTION_KEY"] = ""
for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "UNSPLASH_ACCESS_KEY", "PEXELS_API_KEY"):
    os.environ[name] = ""

from .settings import *  # noqa: E402,F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
PUBLIC_SITE_URL = "http://testserver"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
