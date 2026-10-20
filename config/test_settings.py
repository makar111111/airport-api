import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-key-not-for-deployment")
os.environ.setdefault("DB_ENGINE", "sqlite")
os.environ.setdefault("DJANGO_DEBUG", "True")

from config.settings import *  # noqa: E402,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_CLASSES": [],
}
