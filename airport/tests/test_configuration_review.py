import os
from pathlib import Path
import runpy
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase


class DatabaseConfigurationReviewTests(SimpleTestCase):
    def read_settings(self, **overrides):
        environment = {
            "DJANGO_SECRET_KEY": "configuration-test-key-not-for-deployment",
            "POSTGRES_DB": "test_airport",
            "POSTGRES_USER": "test_user",
            "POSTGRES_PASSWORD": "test-only-password",
            **overrides,
        }
        settings_path = (
            Path(__file__).resolve().parents[2] / "config" / "settings.py"
        )
        with patch.dict(os.environ, environment, clear=True):
            with patch("dotenv.load_dotenv"):
                return runpy.run_path(str(settings_path))

    def test_postgresql_is_default_without_a_database_override(self):
        configuration = self.read_settings()
        self.assertEqual(
            configuration["DATABASES"]["default"]["ENGINE"],
            "django.db.backends.postgresql",
        )

    def test_sqlite_requires_explicit_debug_mode(self):
        for debug in ("False", "false", "0"):
            with self.subTest(debug=debug):
                with self.assertRaisesMessage(
                    ImproperlyConfigured, "SQLite"
                ):
                    self.read_settings(DB_ENGINE="sqlite", DJANGO_DEBUG=debug)

    def test_explicit_sqlite_debug_configuration_remains_available(self):
        configuration = self.read_settings(
            DB_ENGINE="sqlite", DJANGO_DEBUG="True"
        )
        self.assertEqual(
            configuration["DATABASES"]["default"]["ENGINE"],
            "django.db.backends.sqlite3",
        )

    def test_unknown_database_backends_fail_clearly(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "DB_ENGINE"):
            self.read_settings(DB_ENGINE="postgres_typo", DJANGO_DEBUG="True")
