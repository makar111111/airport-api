from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import OperationalError
from django.test import SimpleTestCase


class WaitForDatabaseTests(SimpleTestCase):
    @patch("airport.management.commands.wait_for_db.time.sleep")
    @patch("airport.management.commands.wait_for_db.connection")
    def test_database_ready(self, connection, sleep):
        call_command("wait_for_db", stdout=StringIO())
        connection.ensure_connection.assert_called_once()
        sleep.assert_not_called()

    @patch("airport.management.commands.wait_for_db.time.sleep")
    @patch("airport.management.commands.wait_for_db.connection")
    def test_retries_temporary_failure(self, connection, sleep):
        connection.ensure_connection.side_effect = [OperationalError(), None]
        call_command("wait_for_db", stdout=StringIO())
        self.assertEqual(connection.ensure_connection.call_count, 2)
        sleep.assert_called_once_with(1)

    @patch("airport.management.commands.wait_for_db.time.sleep")
    @patch("airport.management.commands.wait_for_db.connection")
    def test_persistent_failure_is_bounded(self, connection, sleep):
        connection.ensure_connection.side_effect = OperationalError()
        with self.assertRaises(CommandError):
            call_command("wait_for_db", max_retries=2, stdout=StringIO())
        self.assertEqual(connection.ensure_connection.call_count, 2)
        sleep.assert_called_once()

    def test_rejects_invalid_retry_options(self):
        for options in ({"max_retries": 0}, {"interval": -1}):
            with self.subTest(options=options):
                with self.assertRaises(CommandError):
                    call_command("wait_for_db", **options)
