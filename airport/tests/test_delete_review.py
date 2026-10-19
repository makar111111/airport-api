import sqlite3
from unittest.mock import patch

from django.db import IntegrityError

from airport.models import Airport
from airport.tests.helpers import AirportAPITestCase


class CatalogueDeleteReviewTests(AirportAPITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.staff)
        self.unused_airport = Airport.objects.create(
            name="Unused", closest_big_city="Unused city"
        )
        self.delete_url = self.endpoint("airports", self.unused_airport.pk)

    def test_unrelated_integrity_error_propagates(self):
        error = IntegrityError("CHECK constraint failed: unrelated_constraint")
        with patch.object(Airport, "delete", side_effect=error):
            with self.assertRaises(IntegrityError) as caught:
                self.client.delete(self.delete_url)
        self.assertIs(caught.exception, error)
        self.assertTrue(
            Airport.objects.filter(pk=self.unused_airport.pk).exists()
        )

    def test_plain_foreign_key_text_does_not_mask_an_unclassified_error(self):
        error = IntegrityError("FOREIGN KEY constraint failed")
        with patch.object(Airport, "delete", side_effect=error):
            with self.assertRaises(IntegrityError) as caught:
                self.client.delete(self.delete_url)
        self.assertIs(caught.exception, error)

    def test_sqlite_foreign_key_conflict_is_a_validation_error(self):
        cause = sqlite3.IntegrityError("FOREIGN KEY constraint failed")
        cause.sqlite_errorcode = 787
        cause.sqlite_errorname = "SQLITE_CONSTRAINT_FOREIGNKEY"
        error = IntegrityError(str(cause))
        error.__cause__ = cause
        self.assert_reference_error(error)

    def test_postgres_foreign_key_conflict_is_a_validation_error(self):
        cause = Exception("delete violates foreign key constraint")
        cause.sqlstate = "23503"
        error = IntegrityError(str(cause))
        error.__cause__ = cause
        self.assert_reference_error(error)

    def test_protected_object_still_returns_a_validation_error(self):
        response = self.client.delete(
            self.endpoint("airports", self.source.pk)
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("referenced", str(response.data["detail"]))
        self.assertTrue(Airport.objects.filter(pk=self.source.pk).exists())

    def assert_reference_error(self, error):
        with patch.object(Airport, "delete", side_effect=error):
            response = self.client.delete(self.delete_url)
        self.assertEqual(response.status_code, 400)
        self.assertIn("referenced", str(response.data["detail"]))
        self.assertTrue(
            Airport.objects.filter(pk=self.unused_airport.pk).exists()
        )
