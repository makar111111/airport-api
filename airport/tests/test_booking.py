from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

from django.db import (
    close_old_connections, connection, connections, transaction,
)
from django.test import override_settings, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient, APITransactionTestCase

from airport.models import Flight, Order, Ticket
from airport.tests.helpers import AirportAPITestCase


class OrderBookingTests(AirportAPITestCase):
    def test_create_order_reserves_seats_for_authenticated_user(self):
        response = self.book([
            {"flight": self.flight.pk, "row": 1, "seat": 1},
            {"flight": self.flight.pk, "row": 1, "seat": 2},
        ], user=self.staff.pk)
        self.assertEqual(response.status_code, 201)
        order = Order.objects.get(pk=response.data["id"])
        self.assertEqual(order.user, self.user)
        self.assertEqual(order.tickets.count(), 2)

    def test_anonymous_cannot_book(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.book().status_code, 401)
        self.assertEqual(Order.objects.count(), 0)

    def test_duplicate_seat_in_request_rolls_back_entire_order(self):
        ticket = {"flight": self.flight.pk, "row": 1, "seat": 1}
        response = self.book([ticket, ticket])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_taken_seat_rolls_back_all_requested_tickets(self):
        self.create_order(row=1, seat=2)
        response = self.book([
            {"flight": self.flight.pk, "row": 1, "seat": 1},
            {"flight": self.flight.pk, "row": 1, "seat": 2},
        ])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_invalid_seat_bounds_do_not_create_an_order(self):
        for row, seat in [(0, 1), (-1, 1), (5, 1), (1, 0), (1, 7)]:
            with self.subTest(row=row, seat=seat):
                response = self.book([
                    {"flight": self.flight.pk, "row": row, "seat": seat}
                ])
                self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_empty_tickets_and_unknown_flight_are_validation_errors(self):
        self.assertEqual(self.book([]).status_code, 400)
        response = self.book([{"flight": 9999, "row": 1, "seat": 1}])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_departed_flight_cannot_be_booked(self):
        Flight.objects.filter(pk=self.flight.pk).update(
            departure_time=timezone.now() - timedelta(hours=4),
            arrival_time=timezone.now() - timedelta(hours=1),
        )
        self.assertEqual(self.book().status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_multi_flight_failure_rolls_back_every_reservation(self):
        past = Flight.objects.create(
            route=self.route, airplane=self.airplane,
            departure_time=timezone.now() - timedelta(hours=4),
            arrival_time=timezone.now() - timedelta(hours=1),
        )
        response = self.book([
            {"flight": self.flight.pk, "row": 1, "seat": 1},
            {"flight": past.pk, "row": 1, "seat": 1},
        ])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_orders_are_visible_only_to_owner_including_staff(self):
        mine = self.create_order()
        other = self.create_order(user=self.staff, row=1, seat=2)
        response = self.client.get(self.endpoint("orders"))
        self.assertEqual(
            [item["id"] for item in response.data["results"]], [mine.pk]
        )
        self.assertEqual(
            self.client.get(self.endpoint("orders", other.pk)).status_code,
            404,
        )
        self.client.force_authenticate(self.staff)
        self.assertEqual(
            self.client.get(self.endpoint("orders", mine.pk)).status_code,
            404,
        )

    def test_orders_cannot_be_edited_or_deleted(self):
        order = self.create_order()
        url = self.endpoint("orders", order.pk)
        self.assertEqual(self.client.patch(url, {}).status_code, 405)
        self.assertEqual(self.client.delete(url).status_code, 405)
        self.assertTrue(Order.objects.filter(pk=order.pk).exists())


@skipUnlessDBFeature("has_select_for_update")
@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
)
class BookingDeletionRaceTests(APITransactionTestCase):
    def setUp(self):
        AirportAPITestCase.setUp(self)

    def test_delete_waits_for_booking_and_returns_protected_error(self):
        delete_waiting = Event()

        def signal_lock(execute, sql, params, many, context):
            if '"airport_flight"' in sql and (
                "FOR UPDATE" in sql or sql.startswith("DELETE FROM")
            ):
                delete_waiting.set()
            return execute(sql, params, many, context)

        def delete_flight():
            close_old_connections()
            try:
                client = APIClient()
                client.raise_request_exception = False
                client.force_authenticate(self.staff)
                with connection.execute_wrapper(signal_lock):
                    return client.delete(
                        f"/api/airport/flights/{self.flight.pk}/"
                    ).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Flight.objects.select_for_update().get(pk=self.flight.pk)
                order = Order.objects.create(user=self.user)
                Ticket.objects.create(
                    order=order, flight=self.flight, row=1, seat=1
                )
                pending_delete = pool.submit(delete_flight)
                self.assertTrue(delete_waiting.wait(timeout=10))
            self.assertEqual(pending_delete.result(timeout=10), 400)
        self.assertTrue(Flight.objects.filter(pk=self.flight.pk).exists())
        self.assertEqual(Ticket.objects.count(), 1)
