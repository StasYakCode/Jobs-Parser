import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover
    pass

env = os.environ.get

SECRET_KEY = env("SECRET_KEY", "dev-secret-key")
DEBUG = env("DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "jobs",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

if env("DB_ENGINE", "postgres") == "sqlite":  # только для локальных тестов
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "linkedin_jobs"),
        "USER": env("DB_USER", "postgres"),
        "PASSWORD": env("DB_PASSWORD", "1234"),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5432"),
        "CONN_MAX_AGE": 0,
    }}

LANGUAGE_CODE = "ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

PROXY_URL = env("PROXY_URL", "")
REQUEST_DELAY_MIN = float(env("REQUEST_DELAY_MIN", "1.0"))
REQUEST_DELAY_MAX = float(env("REQUEST_DELAY_MAX", "2.5"))
HTTP_TIMEOUT = int(env("HTTP_TIMEOUT", "25"))
HTTP_RETRIES = int(env("HTTP_RETRIES", "4"))
MAX_ATTEMPTS = int(env("MAX_ATTEMPTS", "3"))
RATE_LIMIT_COOLDOWN = int(env("RATE_LIMIT_COOLDOWN", "60"))
STALE_LOCK_MINUTES = int(env("STALE_LOCK_MINUTES", "15"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "std"},
        "file": {"class": "logging.FileHandler", "filename": str(BASE_DIR / "logs" / "parser.log"),
                 "formatter": "std", "encoding": "utf-8"},
    },
    "loggers": {"jobs": {"handlers": ["console", "file"], "level": "INFO"}},
}
