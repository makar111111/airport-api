from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from airport.models import (
    Airplane,
    AirplaneType,
    Airport,
    Crew,
    Flight,
    Order,
    Route,
    Ticket,
)


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
)
class AirportAPITestCase(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="traveller@example.com", password="StrongPassword42!"
        )
        self.staff = get_user_model().objects.create_user(
            email="staff@example.com", password="StrongPassword42!",
            is_staff=True,
        )
        self.source = Airport.objects.create(
            name="Boryspil", closest_big_city="Kyiv"
        )
        self.destination = Airport.objects.create(
            name="Heathrow", closest_big_city="London"
        )
        self.route = Route.objects.create(
            source=self.source, destination=self.destination, distance=2130
        )
        self.airplane_type = AirplaneType.objects.create(name="Airbus A320")
        self.airplane = Airplane.objects.create(
            name="UR-API", rows=4, seats_in_row=6,
            airplane_type=self.airplane_type,
        )
        self.crew = Crew.objects.create(first_name="Ada", last_name="Pilot")
        self.departure = timezone.now() + timedelta(days=2)
        self.flight = Flight.objects.create(
            route=self.route, airplane=self.airplane,
            departure_time=self.departure,
            arrival_time=self.departure + timedelta(hours=3),
        )
        self.flight.crew.add(self.crew)
        self.client.force_authenticate(self.user)

    @staticmethod
    def endpoint(resource, pk=None):
        suffix = f"{pk}/" if pk else ""
        return f"/api/airport/{resource}/{suffix}"

    def book(self, tickets=None, **extra):
        if tickets is None:
            tickets = [{"flight": self.flight.pk, "row": 1, "seat": 1}]
        return self.client.post(
            self.endpoint("orders"), {"tickets": tickets, **extra}
        )

    def create_order(self, user=None, row=1, seat=1, flight=None):
        order = Order.objects.create(user=user or self.user)
        Ticket.objects.create(
            order=order, flight=flight or self.flight, row=row, seat=seat
        )
        return order

    def flight_payload(self, **changes):
        payload = {
            "route": self.route.pk,
            "airplane": self.airplane.pk,
            "crew": [self.crew.pk],
            "departure_time": (
                self.departure + timedelta(days=1)
            ).isoformat(),
            "arrival_time": (
                self.departure + timedelta(days=1, hours=3)
            ).isoformat(),
        }
        return {**payload, **changes}
