import io
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from airport.models import (
    Airplane,
    AirplaneType,
    Airport,
    Crew,
    Flight,
    Order,
    Route,
    Ticket,
    airplane_image_file_path,
)


class AirportModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = Airport.objects.create(
            name="Boryspil", closest_big_city="Kyiv"
        )
        cls.destination = Airport.objects.create(
            name="Heathrow", closest_big_city="London"
        )
        cls.route = Route.objects.create(
            source=cls.source, destination=cls.destination, distance=2130
        )
        cls.airplane_type = AirplaneType.objects.create(name="Boeing 737")
        cls.airplane = Airplane.objects.create(
            name="Sky One",
            rows=20,
            seats_in_row=6,
            airplane_type=cls.airplane_type,
        )
        cls.departure = timezone.now() + timedelta(days=1)
        cls.flight = Flight.objects.create(
            route=cls.route,
            airplane=cls.airplane,
            departure_time=cls.departure,
            arrival_time=cls.departure + timedelta(hours=3),
        )
        cls.user = get_user_model().objects.create_user(
            email="traveller@example.com", password="test-password-123"
        )
        cls.order = Order.objects.create(user=cls.user)

    def make_ticket(self, **overrides):
        return Ticket(
            row=1,
            seat=1,
            flight=self.flight,
            order=self.order,
            **overrides,
        )

    def test_airplane_capacity_uses_rows_and_seats(self):
        self.assertEqual(self.airplane.capacity, 120)

    def test_crew_full_name(self):
        crew = Crew(first_name="Amelia", last_name="Earhart")
        self.assertEqual(crew.full_name, "Amelia Earhart")
        self.assertEqual(str(crew), "Amelia Earhart")

    def test_catalogue_has_readable_string_representations(self):
        self.assertEqual(str(self.source), "Boryspil")
        self.assertEqual(str(self.airplane), "Sky One")
        self.assertEqual(str(self.airplane_type), "Boeing 737")
        self.assertIn("Boryspil", str(self.route))
        self.assertIn("Heathrow", str(self.route))

    def test_route_rejects_same_source_and_destination(self):
        route = Route(
            source=self.source, destination=self.source, distance=10
        )
        with self.assertRaises(ValidationError) as error:
            route.full_clean()
        self.assertIn("destination", error.exception.message_dict)

    def test_route_database_prevents_identical_airports(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Route.objects.create(
                source=self.source, destination=self.source, distance=10
            )

    def test_route_database_prevents_zero_distance(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Route.objects.create(
                source=self.source,
                destination=self.destination,
                distance=0,
            )

    def test_route_exposes_airport_departures_and_arrivals(self):
        self.assertEqual(list(self.source.departures.all()), [self.route])
        self.assertEqual(list(self.destination.arrivals.all()), [self.route])

    def test_airplane_database_prevents_zero_dimensions(self):
        for field in ("rows", "seats_in_row"):
            with self.subTest(field=field):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    Airplane.objects.filter(pk=self.airplane.pk).update(
                        **{field: 0}
                    )

    def test_airplane_type_name_is_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AirplaneType.objects.create(name=self.airplane_type.name)

    def test_airplane_image_is_optional(self):
        self.airplane.full_clean()
        self.assertFalse(self.airplane.image)

    def test_image_names_are_unique_and_ignore_original_name(self):
        stream = io.BytesIO()
        Image.new("RGB", (10, 10), "blue").save(stream, format="JPEG")
        self.airplane.image = SimpleUploadedFile(
            "my-plane.JPG", stream.getvalue(), content_type="image/jpeg"
        )
        first = airplane_image_file_path(self.airplane, "../../my-plane.JPG")
        second = airplane_image_file_path(self.airplane, "../../my-plane.JPG")
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^uploads/airplanes/[0-9a-f-]+\.jpg$")
        self.assertFalse(re.search(r"my-plane|\.\.", first))

    def test_flight_rejects_arrival_before_or_at_departure(self):
        for delta in (timedelta(0), timedelta(minutes=-1)):
            with self.subTest(delta=delta):
                self.flight.arrival_time = self.flight.departure_time + delta
                with self.assertRaises(ValidationError) as error:
                    self.flight.full_clean()
                self.assertIn("arrival_time", error.exception.message_dict)

    def test_flight_database_prevents_invalid_schedule(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Flight.objects.filter(pk=self.flight.pk).update(
                arrival_time=self.flight.departure_time
            )

    def test_flight_preserves_timezone_aware_times(self):
        self.flight.refresh_from_db()
        self.assertTrue(timezone.is_aware(self.flight.departure_time))
        self.assertTrue(timezone.is_aware(self.flight.arrival_time))

    def test_flights_order_by_departure_time(self):
        earlier = Flight.objects.create(
            route=self.route,
            airplane=self.airplane,
            departure_time=self.departure - timedelta(hours=5),
            arrival_time=self.departure - timedelta(hours=2),
        )
        self.assertEqual(list(Flight.objects.all()), [earlier, self.flight])

    def test_flight_supports_multiple_crew_members(self):
        captain = Crew.objects.create(first_name="Jane", last_name="Smith")
        pilot = Crew.objects.create(first_name="John", last_name="Doe")
        self.flight.crew.add(captain, pilot)
        self.assertCountEqual(self.flight.crew.all(), [captain, pilot])

    def test_ticket_accepts_last_seat_in_last_row(self):
        ticket = Ticket.objects.create(
            row=self.airplane.rows,
            seat=self.airplane.seats_in_row,
            flight=self.flight,
            order=self.order,
        )
        self.assertEqual(self.flight.tickets.get(), ticket)
        self.assertEqual(self.order.tickets.get(), ticket)

    def test_ticket_save_rejects_rows_outside_airplane(self):
        for row in (0, -1, self.airplane.rows + 1):
            with self.subTest(row=row):
                ticket = self.make_ticket()
                ticket.row = row
                with self.assertRaises(ValidationError) as error:
                    ticket.save()
                self.assertIn("row", error.exception.message_dict)
        self.assertFalse(Ticket.objects.exists())

    def test_ticket_save_rejects_seats_outside_airplane(self):
        for seat in (0, -1, self.airplane.seats_in_row + 1):
            with self.subTest(seat=seat):
                ticket = self.make_ticket()
                ticket.seat = seat
                with self.assertRaises(ValidationError) as error:
                    ticket.save()
                self.assertIn("seat", error.exception.message_dict)

    def test_ticket_validation_handles_invalid_flight_reference(self):
        ticket = Ticket(row=1, seat=1, flight_id=99999, order=self.order)
        with self.assertRaises(ValidationError) as error:
            ticket.full_clean()
        self.assertIn("flight", error.exception.message_dict)

    def test_ticket_validation_handles_missing_flight_and_bad_row(self):
        ticket = Ticket(row="not-a-row", seat=1, order=self.order)
        with self.assertRaises(ValidationError) as error:
            ticket.full_clean()
        self.assertIn("flight", error.exception.message_dict)
        self.assertIn("row", error.exception.message_dict)

    def test_ticket_validation_handles_bad_coordinate_types(self):
        ticket = self.make_ticket()
        ticket.row = "not-a-row"
        ticket.seat = "not-a-seat"
        with self.assertRaises(ValidationError) as error:
            ticket.full_clean()
        self.assertIn("row", error.exception.message_dict)
        self.assertIn("seat", error.exception.message_dict)

    def test_ticket_database_prevents_duplicate_booking(self):
        self.make_ticket().save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Ticket.objects.bulk_create([self.make_ticket()])

    def test_ticket_database_prevents_zero_coordinates(self):
        for field in ("row", "seat"):
            with self.subTest(field=field):
                ticket = self.make_ticket()
                setattr(ticket, field, 0)
                with self.assertRaises(IntegrityError), transaction.atomic():
                    Ticket.objects.bulk_create([ticket])

    def test_same_seat_can_be_booked_on_another_flight(self):
        self.make_ticket().save()
        another_flight = Flight.objects.create(
            route=self.route,
            airplane=self.airplane,
            departure_time=self.departure + timedelta(days=1),
            arrival_time=self.departure + timedelta(days=1, hours=3),
        )
        Ticket.objects.create(
            row=1, seat=1, flight=another_flight, order=self.order
        )
        self.assertEqual(Ticket.objects.count(), 2)

    def test_ticket_save_supports_update_fields(self):
        ticket = self.make_ticket()
        ticket.save()
        ticket.seat = 2
        ticket.save(update_fields=["seat"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.seat, 2)

    def test_tickets_are_ordered_by_row_then_seat(self):
        for row, seat in ((2, 1), (1, 2), (1, 1)):
            Ticket.objects.create(
                row=row, seat=seat, flight=self.flight, order=self.order
            )
        self.assertEqual(
            list(Ticket.objects.values_list("row", "seat")),
            [(1, 1), (1, 2), (2, 1)],
        )

    def test_orders_are_newest_first(self):
        newer = Order.objects.create(user=self.user)
        self.assertEqual(list(Order.objects.all()), [newer, self.order])

    def test_order_delete_removes_its_tickets(self):
        self.make_ticket().save()
        self.order.delete()
        self.assertFalse(Ticket.objects.exists())

    def test_referenced_catalogue_and_booked_flight_are_protected(self):
        self.make_ticket().save()
        for entity in (
            self.source,
            self.destination,
            self.route,
            self.airplane_type,
            self.airplane,
            self.flight,
        ):
            with self.subTest(entity=entity):
                with self.assertRaises(ProtectedError):
                    entity.delete()

    def login_admin(self):
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save(update_fields=["is_staff", "is_superuser"])
        self.client.force_login(self.user)

    def test_admin_cannot_change_booked_airplane_dimensions(self):
        self.make_ticket().save()
        self.login_admin()
        response = self.client.post(
            reverse("admin:airport_airplane_change", args=[self.airplane.pk]),
            {
                "name": "Renamed Sky One",
                "airplane_type": self.airplane_type.pk,
                "rows": 1,
                "seats_in_row": 1,
                "_save": "Save",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.airplane.refresh_from_db()
        self.assertEqual(self.airplane.name, "Renamed Sky One")
        self.assertEqual(self.airplane.rows, 20)
        self.assertEqual(self.airplane.seats_in_row, 6)

    def test_admin_cannot_change_airports_on_a_booked_route(self):
        self.make_ticket().save()
        self.login_admin()
        response = self.client.post(
            reverse("admin:airport_route_change", args=[self.route.pk]),
            {
                "source": self.destination.pk,
                "destination": self.source.pk,
                "distance": 2200,
                "_save": "Save",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.route.refresh_from_db()
        self.assertEqual(self.route.source, self.source)
        self.assertEqual(self.route.destination, self.destination)
        self.assertEqual(self.route.distance, 2200)

    def test_admin_cannot_change_booked_flight_schedule_or_crew(self):
        crew = Crew.objects.create(first_name="Jane", last_name="Smith")
        self.flight.crew.add(crew)
        self.make_ticket().save()
        self.login_admin()
        response = self.client.post(
            reverse("admin:airport_flight_change", args=[self.flight.pk]),
            {
                "route": self.route.pk,
                "airplane": self.airplane.pk,
                "departure_time_0": "2030-01-01",
                "departure_time_1": "10:00:00",
                "arrival_time_0": "2030-01-01",
                "arrival_time_1": "13:00:00",
                "crew": [],
                "_save": "Save",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.flight.refresh_from_db()
        self.assertEqual(self.flight.departure_time, self.departure)
        self.assertEqual(
            self.flight.arrival_time, self.departure + timedelta(hours=3)
        )
        self.assertEqual(list(self.flight.crew.all()), [crew])

    def flight_admin_data(self, **overrides):
        data = {
            "route": self.route.pk,
            "airplane": self.airplane.pk,
            "departure_time_0": self.departure.date().isoformat(),
            "departure_time_1": self.departure.strftime("%H:%M:%S"),
            "arrival_time_0": (
                self.departure + timedelta(hours=2)
            ).date().isoformat(),
            "arrival_time_1": (
                self.departure + timedelta(hours=2)
            ).strftime("%H:%M:%S"),
            "_save": "Save",
        }
        data.update(overrides)
        return data

    def test_admin_rejects_overlapping_airplane_schedule(self):
        self.login_admin()
        response = self.client.post(
            reverse("admin:airport_flight_add"), self.flight_admin_data()
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("airplane", response.context["adminform"].form.errors)
        self.assertEqual(Flight.objects.count(), 1)

    def test_admin_rejects_overlapping_crew_schedule(self):
        crew = Crew.objects.create(first_name="Jane", last_name="Smith")
        self.flight.crew.add(crew)
        another_airplane = Airplane.objects.create(
            name="Sky Two", rows=20, seats_in_row=6,
            airplane_type=self.airplane_type,
        )
        self.login_admin()
        response = self.client.post(
            reverse("admin:airport_flight_add"),
            self.flight_admin_data(
                airplane=another_airplane.pk, crew=[crew.pk]
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("crew", response.context["adminform"].form.errors)
        self.assertEqual(Flight.objects.count(), 1)

    def test_admin_allows_viewing_bookings(self):
        ticket = self.make_ticket()
        ticket.save()
        self.login_admin()
        for model, instance in (("order", self.order), ("ticket", ticket)):
            with self.subTest(model=model):
                response = self.client.get(reverse(
                    f"admin:airport_{model}_change", args=[instance.pk]
                ))
                self.assertEqual(response.status_code, 200)

    def test_admin_cannot_create_orders_or_tickets(self):
        self.login_admin()
        for model in ("order", "ticket"):
            with self.subTest(model=model):
                url = reverse(f"admin:airport_{model}_add")
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_admin_cannot_change_or_delete_orders_or_tickets(self):
        ticket = self.make_ticket()
        ticket.save()
        self.login_admin()
        for model, instance in (("order", self.order), ("ticket", ticket)):
            with self.subTest(model=model):
                change_url = reverse(
                    f"admin:airport_{model}_change", args=[instance.pk]
                )
                delete_url = reverse(
                    f"admin:airport_{model}_delete", args=[instance.pk]
                )
                self.assertEqual(
                    self.client.post(change_url, {}).status_code, 403
                )
                self.assertEqual(self.client.get(delete_url).status_code, 403)
                self.assertEqual(
                    self.client.post(delete_url, {"post": "yes"}).status_code,
                    403,
                )
        self.assertTrue(Order.objects.filter(pk=self.order.pk).exists())
        self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())
