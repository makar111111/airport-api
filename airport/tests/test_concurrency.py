"""Real PostgreSQL transactions; SQLite deliberately skips these checks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from airport.models import (
    Airplane, AirplaneType, Airport, Flight, Order, Route, Ticket,
)


@skipUnlessDBFeature("has_select_for_update")
class ConcurrentRequestsTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="race@example.com", password="test-password", is_staff=True,
        )
        source = Airport.objects.create(name="A", closest_big_city="City A")
        destination = Airport.objects.create(
            name="B", closest_big_city="City B",
        )
        self.route = Route.objects.create(
            source=source, destination=destination, distance=100,
        )
        airplane_type = AirplaneType.objects.create(name="Test type")
        self.airplane = Airplane.objects.create(
            name="Test airplane", rows=2, seats_in_row=2,
            airplane_type=airplane_type,
        )
        self.departure = timezone.now() + timedelta(days=1)

    def simultaneous_posts(self, url, payload):
        barrier = Barrier(2)

        def request():
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(self.user)
                barrier.wait(timeout=10)
                response = client.post(url, payload, format="json")
                return response.status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(request) for _ in range(2)]
            return sorted(future.result(timeout=20) for future in futures)

    def test_simultaneous_reservations_sell_a_seat_once(self):
        flight = Flight.objects.create(
            route=self.route, airplane=self.airplane,
            departure_time=self.departure,
            arrival_time=self.departure + timedelta(hours=1),
        )
        statuses = self.simultaneous_posts(
            reverse("airport:order-list"),
            {"tickets": [{"flight": flight.pk, "row": 1, "seat": 1}]},
        )
        self.assertEqual(statuses, [201, 400])
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_simultaneous_schedules_use_an_airplane_once(self):
        statuses = self.simultaneous_posts(
            reverse("airport:flight-list"),
            {
                "route": self.route.pk, "airplane": self.airplane.pk,
                "crew": [], "departure_time": self.departure.isoformat(),
                "arrival_time": (
                    self.departure + timedelta(hours=1)
                ).isoformat(),
            },
        )
        self.assertEqual(statuses, [201, 400])
        self.assertEqual(Flight.objects.count(), 1)
