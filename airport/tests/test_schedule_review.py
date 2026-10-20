"""Schedule, resource-lock and database constraint regressions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.db import (
    IntegrityError, close_old_connections, connection, connections,
    transaction,
)
from django.test import override_settings, skipUnlessDBFeature
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITransactionTestCase

from airport.db_errors import is_airplane_overlap
from airport.models import Airplane, AirplaneType, Flight, Order, Route, Ticket
from airport.services import save_flight, update_airplane
from airport.tests.helpers import AirportAPITestCase


class BookedAirplaneReviewTests(AirportAPITestCase):
    def test_booked_airplane_type_cannot_change_through_service(self):
        self.create_order()
        another_type = AirplaneType.objects.create(name="Boeing 737")
        with self.assertRaises(ValidationError):
            update_airplane(instance=self.airplane, data={
                "airplane_type": another_type,
            })
        self.airplane.refresh_from_db()
        self.assertEqual(self.airplane.airplane_type, self.airplane_type)

    def test_booked_airplane_type_cannot_change_through_api(self):
        self.create_order()
        another_type = AirplaneType.objects.create(name="Boeing 737")
        self.client.force_authenticate(self.staff)
        response = self.client.patch(
            self.endpoint("airplanes", self.airplane.pk),
            {"airplane_type": another_type.pk},
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.airplane.refresh_from_db()
        self.assertEqual(self.airplane.airplane_type, self.airplane_type)

    def test_unbooked_airplane_type_can_change(self):
        another_type = AirplaneType.objects.create(name="Boeing 737")
        update_airplane(instance=self.airplane, data={
            "airplane_type": another_type,
        })
        self.airplane.refresh_from_db()
        self.assertEqual(self.airplane.airplane_type, another_type)

    def test_booked_airplane_allows_unchanged_type_and_name_update(self):
        self.create_order()
        update_airplane(instance=self.airplane, data={
            "airplane_type": self.airplane_type, "name": "Updated name",
        })
        self.airplane.refresh_from_db()
        self.assertEqual(self.airplane.name, "Updated name")


class ScheduleErrorReviewTests(AirportAPITestCase):
    def test_unrelated_integrity_failure_is_preserved(self):
        error = IntegrityError("Unrelated integrity failure")
        with patch("airport.services.Flight.save", side_effect=error):
            with self.assertRaises(IntegrityError) as caught:
                save_flight(data={
                    "route": self.route, "airplane": self.airplane,
                    "crew": [],
                    "departure_time": self.departure + timedelta(days=1),
                    "arrival_time": self.departure + timedelta(
                        days=1, hours=1,
                    ),
                })
        self.assertIs(caught.exception, error)
        self.assertEqual(Flight.objects.count(), 1)


@skipUnless(
    connection.vendor == "postgresql", "PostgreSQL exclusion constraint",
)
class PostgreSQLAirplaneConstraintTests(AirportAPITestCase):
    def test_direct_orm_insert_rejects_overlapping_airplane(self):
        reverse_route = Route.objects.create(
            source=self.destination, destination=self.source, distance=2130,
        )
        with self.assertRaises(IntegrityError) as caught:
            with transaction.atomic():
                Flight.objects.create(
                    route=reverse_route, airplane=self.airplane,
                    departure_time=self.departure + timedelta(hours=1),
                    arrival_time=self.departure + timedelta(hours=2),
                )
        self.assertTrue(is_airplane_overlap(caught.exception))
        self.assertEqual(Flight.objects.count(), 1)

    def test_direct_orm_update_rejects_overlapping_airplane(self):
        another = Flight.objects.create(
            route=self.route, airplane=self.airplane,
            departure_time=self.departure + timedelta(days=1),
            arrival_time=self.departure + timedelta(days=1, hours=3),
        )
        with self.assertRaises(IntegrityError) as caught:
            with transaction.atomic():
                Flight.objects.filter(pk=another.pk).update(
                    departure_time=self.departure + timedelta(hours=1),
                    arrival_time=self.departure + timedelta(hours=2),
                )
        self.assertTrue(is_airplane_overlap(caught.exception))
        another.refresh_from_db()
        self.assertEqual(
            another.departure_time, self.departure + timedelta(days=1),
        )

    def test_direct_orm_allows_adjacent_boundaries(self):
        Flight.objects.create(
            route=self.route, airplane=self.airplane,
            departure_time=self.departure - timedelta(hours=1),
            arrival_time=self.departure,
        )
        Flight.objects.create(
            route=self.route, airplane=self.airplane,
            departure_time=self.flight.arrival_time,
            arrival_time=self.flight.arrival_time + timedelta(hours=1),
        )
        self.assertEqual(Flight.objects.count(), 3)

    def test_constraint_failure_is_translated_by_service_with_cause(self):
        # The database still protects a writer that bypasses schedule checks.
        with patch("airport.services._validate_flight"):
            with self.assertRaises(ValidationError) as caught:
                save_flight(data={
                    "route": self.route, "airplane": self.airplane,
                    "crew": [], "departure_time": self.departure,
                    "arrival_time": self.departure + timedelta(hours=1),
                })
        self.assertIn("airplane", caught.exception.detail)
        self.assertTrue(is_airplane_overlap(caught.exception.__cause__))
        self.assertEqual(Flight.objects.count(), 1)


@skipUnlessDBFeature("has_select_for_update")
@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class ContendedResourceReviewTests(APITransactionTestCase):
    def setUp(self):
        AirportAPITestCase.setUp(self)
        self.other_route = Route.objects.create(
            source=self.destination, destination=self.source, distance=2130,
        )
        self.other_airplane = Airplane.objects.create(
            name="UR-SECOND", rows=4, seats_in_row=6,
            airplane_type=self.airplane_type,
        )

    def contended_posts(
        self, *, url, first_payload, second_payload, resource, insert_table,
    ):
        """Hold the first insert after its locks, then start the contender."""
        first_inserted = Event()
        release_first = Event()
        second_lock_attempted = Event()

        def first_wrapper(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if sql.startswith(f'INSERT INTO "{insert_table}"'):
                first_inserted.set()
                if not release_first.wait(timeout=15):
                    raise AssertionError("First request was not released")
            return result

        def second_wrapper(execute, sql, params, many, context):
            if f'"{resource}"' in sql and "FOR UPDATE" in sql:
                second_lock_attempted.set()
            return execute(sql, params, many, context)

        def request(payload, wrapper):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(self.staff)
                with connection.execute_wrapper(wrapper):
                    return client.post(url, payload, format="json").status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(request, first_payload, first_wrapper)
            try:
                self.assertTrue(first_inserted.wait(timeout=10))
                second = pool.submit(request, second_payload, second_wrapper)
                self.assertTrue(second_lock_attempted.wait(timeout=10))
                self.assertFalse(second.done())
            finally:
                release_first.set()
            return first.result(timeout=15), second.result(timeout=15)

    def schedule_payload(self, *, airplane, route, crew):
        return {
            "route": route.pk, "airplane": airplane.pk,
            "crew": [member.pk for member in crew],
            "departure_time": (
                self.departure + timedelta(days=1)
            ).isoformat(),
            "arrival_time": (
                self.departure + timedelta(days=1, hours=2)
            ).isoformat(),
        }

    def test_shared_crew_serializes_different_airplanes_and_routes(self):
        statuses = self.contended_posts(
            url="/api/airport/flights/",
            first_payload=self.schedule_payload(
                airplane=self.airplane, route=self.route, crew=[self.crew],
            ),
            second_payload=self.schedule_payload(
                airplane=self.other_airplane, route=self.other_route,
                crew=[self.crew],
            ),
            resource="airport_crew", insert_table="airport_flight",
        )
        self.assertEqual(statuses, (201, 400))
        self.assertEqual(Flight.objects.count(), 2)
        self.assertEqual(self.crew.flights.count(), 2)

    def test_shared_airplane_serializes_different_routes(self):
        statuses = self.contended_posts(
            url="/api/airport/flights/",
            first_payload=self.schedule_payload(
                airplane=self.airplane, route=self.route, crew=[],
            ),
            second_payload=self.schedule_payload(
                airplane=self.airplane, route=self.other_route, crew=[],
            ),
            resource="airport_airplane", insert_table="airport_flight",
        )
        self.assertEqual(statuses, (201, 400))
        self.assertEqual(Flight.objects.count(), 2)

    def test_concurrent_same_seat_requests_create_one_ticket_and_order(self):
        payload = {"tickets": [
            {"flight": self.flight.pk, "row": 1, "seat": 1},
        ]}
        statuses = self.contended_posts(
            url="/api/airport/orders/", first_payload=payload,
            second_payload=payload, resource="airport_route",
            insert_table="airport_order",
        )
        self.assertEqual(statuses, (201, 400))
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Ticket.objects.count(), 1)
