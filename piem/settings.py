from pathlib import Path
import os
import environ

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="G0NjRvqsCvevBJxp81IV_IfgoDA6KC9XlRQmfcoVfvY")
DEBUG = env("DEBUG", default=True)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])


INSTALLED_APPS = [
    "django.contrib.admin", 
    "django.contrib.auth", 
    "django.contrib.contenttypes",
    "django.contrib.sessions", 
    "django.contrib.messages", 
    "django.contrib.staticfiles", 
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware", 
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", 
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "piem.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates", 
        "DIRS": [], 
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request", 
                "django.contrib.auth.context_processors.auth", 
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.version_context", # Injeta versão do site em todos os templates
            ]
        }
    }
]

WSGI_APPLICATION = "piem.wsgi.application"

# ==============================================================================
# CONFIGURAÇÃO DE BANCO DE DADOS ESTRUTURADO (SQL / POSTGRESQL / SUPABASE)
# ==============================================================================
# Para conectar o site diretamente ao Supabase via PostgreSQL:
# Set no seu arquivo .env:
#   DB_ENGINE=django.db.backends.postgresql
#   DB_NAME=postgres
#   DB_USER=postgres.[SEU-PROJETO-SUPABASE]
#   DB_PASSWORD=[SUA-SENHA-SUPABASE]
#   DB_HOST=aws-0-sa-east-1.pooler.supabase.com (ou db.[REF].supabase.co)
#   DB_PORT=6543 (ou 5432)
# ==============================================================================

USE_POSTGRES = env.bool("USE_POSTGRES", default=False)

if USE_POSTGRES:
    DATABASES = {
        "default": {
            "ENGINE": env("DB_ENGINE", default="django.db.backends.postgresql"),
            "NAME": env("DB_NAME", default="postgres"),
            "USER": env("DB_USER", default="postgres"),
            "PASSWORD": env("DB_PASSWORD", default=""),
            "HOST": env("DB_HOST", default="localhost"),
            "PORT": env("DB_PORT", default="5432"),
            "OPTIONS": {
                "sslmode": env("DB_SSLMODE", default="require"),
            }
        }
    }
else:
    # Modo Local padrão caso o PostgreSQL/Supabase ainda não esteja com credenciais no .env
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3", 
            "NAME": BASE_DIR / "db.sqlite3"
        }
    }

AUTH_USER_MODEL = "core.User"
AUTH_PASSWORD_VALIDATORS = [{"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"}]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "assets"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL = env("REDIS_URL", default="")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "piem-enterprise-cache",
        }
    }

SAFE_REPORT_ENCRYPTION_KEY = env("SAFE_REPORT_ENCRYPTION_KEY", default="")
PHP_BRIDGE_SECRET = env("PHP_BRIDGE_SECRET", default="")
PUBLIC_SITE_URL = env("PUBLIC_SITE_URL", default="http://127.0.0.1:8000" if DEBUG else "").rstrip("/")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=not DEBUG)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=not DEBUG)
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LOGIN_URL = "login_aluno"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "home"
