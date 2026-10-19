"""Booking regressions identified during review."""

from datetime import timedelta
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from airport.db_errors import (
    is_airplane_overlap, is_reference_conflict, is_seat_conflict,
)
from airport.models import Flight, Order, Ticket
from airport.services import reserve_order
from airport.tests.helpers import AirportAPITestCase


class ReservationReviewTests(AirportAPITestCase):
    def another_flight(self):
        return Flight.objects.create(
            route=self.route, airplane=self.airplane,
            departure_time=self.departure + timedelta(days=1),
            arrival_time=self.departure + timedelta(days=1, hours=3),
        )

    def test_duplicate_place_is_rejected_before_database_queries(self):
        ticket = {"flight": self.flight, "row": 1, "seat": 1}
        with self.assertNumQueries(0):
            with self.assertRaises(ValidationError):
                reserve_order(user=self.user, tickets=[ticket, ticket])
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Ticket.objects.exists())

    def test_service_accepts_distinct_seats_and_multiple_flights(self):
        another = self.another_flight()
        order = reserve_order(user=self.user, tickets=[
            {"flight": another, "row": 1, "seat": 1},
            {"flight": self.flight, "row": 1, "seat": 2},
            {"flight": self.flight, "row": 1, "seat": 1},
        ])
        self.assertEqual(order.user, self.user)
        self.assertCountEqual(
            order.tickets.values_list("flight_id", "row", "seat"),
            [(another.pk, 1, 1), (self.flight.pk, 1, 1),
             (self.flight.pk, 1, 2)],
        )

    def test_api_accepts_distinct_seats_on_each_requested_flight(self):
        another = self.another_flight()
        response = self.book([
            {"flight": self.flight.pk, "row": 1, "seat": 1},
            {"flight": self.flight.pk, "row": 1, "seat": 2},
            {"flight": another.pk, "row": 1, "seat": 1},
        ])
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Ticket.objects.count(), 3)

    def test_unrelated_integrity_error_is_preserved_and_rolled_back(self):
        error = IntegrityError("Unrelated database integrity failure")
        with patch(
            "airport.services.Ticket.objects.bulk_create", side_effect=error,
        ):
            with self.assertRaises(IntegrityError) as caught:
                reserve_order(user=self.user, tickets=[
                    {"flight": self.flight, "row": 1, "seat": 1},
                ])
        self.assertIs(caught.exception, error)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Ticket.objects.exists())

    def test_partial_multi_flight_write_rolls_back_on_unrelated_error(self):
        another = self.another_flight()

        def fail_after_first_insert(tickets):
            # Simulate the second write failing after the first insert; use a
            # real database write so transaction rollback is observable.
            tickets[0].save()
            raise IntegrityError("Unrelated failure on the next insert")

        with patch(
            "airport.services.Ticket.objects.bulk_create",
            side_effect=fail_after_first_insert,
        ):
            with self.assertRaises(IntegrityError):
                reserve_order(user=self.user, tickets=[
                    {"flight": self.flight, "row": 1, "seat": 1},
                    {"flight": another, "row": 1, "seat": 1},
                ])
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Ticket.objects.exists())

    def test_invalid_second_flight_reserves_nothing(self):
        another = self.another_flight()
        response = self.book([
            {"flight": self.flight.pk, "row": 1, "seat": 1},
            {"flight": another.pk, "row": 5, "seat": 1},
        ])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Ticket.objects.exists())

    def test_database_seat_constraint_is_recognized(self):
        order = self.create_order()
        with self.assertRaises(IntegrityError) as caught:
            with transaction.atomic():
                Ticket.objects.bulk_create([
                    Ticket(order=order, flight=self.flight, row=1, seat=1),
                ])
        self.assertTrue(is_seat_conflict(caught.exception))
        self.assertFalse(is_reference_conflict(caught.exception))

    def test_seat_constraint_error_has_validation_response_and_cause(self):
        order = self.create_order()
        with self.assertRaises(IntegrityError) as caught:
            with transaction.atomic():
                Ticket.objects.bulk_create([
                    Ticket(order=order, flight=self.flight, row=1, seat=1),
                ])
        # Reproduce the driver failure arriving after the service's seat check.
        with patch(
            "airport.services.Ticket.objects.bulk_create",
            side_effect=caught.exception,
        ):
            with self.assertRaises(ValidationError) as validation:
                reserve_order(user=self.user, tickets=[
                    {"flight": self.flight, "row": 1, "seat": 2},
                ])
        self.assertIs(validation.exception.__cause__, caught.exception)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_unrelated_integrity_failure_returns_logged_server_error(self):
        error = IntegrityError("Unrelated database integrity failure")
        self.client.raise_request_exception = False
        with patch(
            "airport.services.Ticket.objects.bulk_create", side_effect=error,
        ):
            with self.assertLogs("django.request", level="ERROR") as logs:
                response = self.book()
        self.assertEqual(response.status_code, 500)
        self.assertIs(logs.records[0].exc_info[1], error)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Ticket.objects.exists())


class ConstraintClassificationTests(SimpleTestCase):
    @staticmethod
    def postgres_error(sqlstate, name, *, psycopg2=False):
        driver_error = Exception("Driver diagnostics, not message parsing")
        setattr(driver_error, "pgcode" if psycopg2 else "sqlstate", sqlstate)
        driver_error.diag = SimpleNamespace(constraint_name=name)
        error = IntegrityError("Django database wrapper")
        error.__cause__ = driver_error
        return error

    def test_postgres_seat_conflict_requires_both_code_and_constraint(self):
        self.assertTrue(is_seat_conflict(self.postgres_error(
            "23505", "unique_flight_seat",
        )))
        self.assertTrue(is_seat_conflict(self.postgres_error(
            "23505", "unique_flight_seat", psycopg2=True,
        )))
        for code, name in [
            ("23505", "another_unique_constraint"),
            ("23514", "unique_flight_seat"),
            ("23503", "unique_flight_seat"),
        ]:
            with self.subTest(code=code, name=name):
                self.assertFalse(is_seat_conflict(
                    self.postgres_error(code, name),
                ))

    def test_postgres_reference_conflict_requires_foreign_key_code(self):
        self.assertTrue(is_reference_conflict(self.postgres_error(
            "23503", "airport_flight_route_id_fk",
        )))
        self.assertFalse(is_reference_conflict(self.postgres_error(
            "23514", "airport_flight_route_id_fk",
        )))

    def test_sqlite_uses_native_type_and_exact_unique_column_signature(self):
        signature = (
            "UNIQUE constraint failed: airport_ticket.flight_id, "
            "airport_ticket.row, airport_ticket.seat"
        )
        self.assertTrue(is_seat_conflict(sqlite3.IntegrityError(signature)))
        for error in [
            IntegrityError(signature),
            sqlite3.IntegrityError(signature + ", airport_ticket.order_id"),
            sqlite3.IntegrityError(
                "UNIQUE constraint failed: user_user.email",
            ),
            sqlite3.IntegrityError(
                "CHECK constraint failed: ticket_row_positive",
            ),
        ]:
            with self.subTest(error=error):
                self.assertFalse(is_seat_conflict(error))

    def test_sqlite_foreign_key_code_or_exact_legacy_signature(self):
        self.assertTrue(is_reference_conflict(
            sqlite3.IntegrityError("FOREIGN KEY constraint failed"),
        ))
        foreign_key = sqlite3.IntegrityError("Driver-provided error")
        foreign_key.sqlite_errorcode = 787
        self.assertTrue(is_reference_conflict(foreign_key))
        check_error = sqlite3.IntegrityError("FOREIGN KEY constraint failed")
        check_error.sqlite_errorcode = 275
        self.assertFalse(is_reference_conflict(check_error))
        self.assertFalse(is_reference_conflict(
            IntegrityError("FOREIGN KEY constraint failed"),
        ))

    def test_airplane_overlap_requires_its_named_exclusion_constraint(self):
        self.assertTrue(is_airplane_overlap(self.postgres_error(
            "23P01", "flight_airplane_no_overlap",
        )))
        self.assertFalse(is_airplane_overlap(self.postgres_error(
            "23P01", "another_exclusion_constraint",
        )))
        self.assertFalse(is_airplane_overlap(self.postgres_error(
            "23505", "flight_airplane_no_overlap",
        )))
