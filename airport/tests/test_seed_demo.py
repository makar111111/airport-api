from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from airport.models import (
    Airplane, AirplaneType, Airport, Crew, Flight, Order, Route, Ticket,
)


NOW = datetime(2026, 10, 18, 23, 45, tzinfo=timezone.utc)


class SeedDemoTests(TestCase):
    def seed(self, now=NOW):
        with patch("django.utils.timezone.now", return_value=now):
            call_command("seed_demo", stdout=StringIO())

    def test_creates_related_future_flights_without_users(self):
        self.seed()
        self.assertEqual(Airport.objects.count(), 4)
        self.assertEqual(Route.objects.count(), 6)
        self.assertEqual(AirplaneType.objects.count(), 3)
        self.assertEqual(Airplane.objects.count(), 3)
        self.assertEqual(Crew.objects.count(), 4)
        self.assertEqual(Flight.objects.count(), 6)
        self.assertFalse(get_user_model().objects.exists())
        for flight in Flight.objects.all():
            self.assertGreater(flight.departure_time, NOW)
            self.assertGreater(flight.arrival_time, flight.departure_time)
            self.assertIsNotNone(flight.departure_time.utcoffset())
            self.assertIn(
                flight.departure_time.date(),
                ((NOW + timedelta(days=1)).date(),
                 (NOW + timedelta(days=2)).date()),
            )
            self.assertEqual(flight.crew.count(), 2)

    def test_repeat_same_day_does_not_duplicate_or_reset_assignments(self):
        self.seed()
        before = list(Flight.objects.values())
        assignments = list(
            Flight.crew.through.objects.order_by("pk").values()
        )
        self.seed(NOW - timedelta(hours=2))
        self.assertEqual(list(Flight.objects.values()), before)
        self.assertEqual(
            list(Flight.crew.through.objects.order_by("pk").values()),
            assignments,
        )
        self.assertEqual(Airport.objects.count(), 4)
        self.assertEqual(Route.objects.count(), 6)
        self.assertEqual(Airplane.objects.count(), 3)
        self.assertEqual(Crew.objects.count(), 4)

    def test_seed_preserves_existing_bookings_and_edited_sample_data(self):
        self.seed()
        flight = Flight.objects.first()
        user = get_user_model().objects.create_user("passenger@example.com")
        order = Order.objects.create(user=user)
        ticket = Ticket.objects.create(
            order=order, flight=flight, row=1, seat=1
        )
        flight.arrival_time += timedelta(minutes=30)
        flight.save()
        original_crew = list(flight.crew.values_list("pk", flat=True))[:1]
        flight.crew.set(original_crew)
        airplane = flight.airplane
        airplane.rows = 25
        airplane.save()
        route = flight.route
        route.distance = 999
        route.save()
        before = list(Flight.objects.values())

        self.seed()

        ticket.refresh_from_db()
        flight.refresh_from_db()
        airplane.refresh_from_db()
        route.refresh_from_db()
        self.assertEqual(ticket.flight_id, flight.pk)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(list(Flight.objects.values()), before)
        self.assertEqual(
            list(flight.crew.values_list("pk", flat=True)), original_crew
        )
        self.assertEqual(airplane.rows, 25)
        self.assertEqual(route.distance, 999)

    def test_no_airplane_or_crew_has_overlapping_flights(self):
        self.seed()
        for resource in [*Airplane.objects.all(), *Crew.objects.all()]:
            flights = list(resource.flights.order_by("departure_time"))
            for previous, following in zip(flights, flights[1:]):
                self.assertLessEqual(
                    previous.arrival_time, following.departure_time
                )

    def test_existing_schedule_is_preserved_when_demo_slot_conflicts(self):
        self.seed()
        original = Flight.objects.first()
        departure, arrival = original.departure_time, original.arrival_time
        airplane = original.airplane
        other_route = Route.objects.exclude(pk=original.route_id).first()
        original.delete()
        Flight.objects.create(
            route=other_route, airplane=airplane,
            departure_time=departure - timedelta(minutes=30),
            arrival_time=arrival + timedelta(minutes=30),
        )
        before = list(Flight.objects.values())

        self.seed()

        self.assertEqual(list(Flight.objects.values()), before)
