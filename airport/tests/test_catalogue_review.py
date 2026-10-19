from datetime import timedelta
from types import SimpleNamespace

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator

from airport.admin import AirplaneAdmin, AirplaneAdminForm
from airport.models import Airplane, AirplaneType, Airport, Crew, Order, Route
from airport.serializers import OrderCreateSerializer, TicketRequestSerializer
from airport.tests.helpers import AirportAPITestCase


class CatalogueReviewTests(AirportAPITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.staff)

    def test_airport_name_is_unique_in_api_and_database(self):
        response = self.client.post(self.endpoint("airports"), {
            "name": self.source.name, "closest_big_city": "Another city",
        })
        self.assertEqual(response.status_code, 400)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Airport.objects.bulk_create([
                Airport(name=self.source.name, closest_big_city="Other"),
            ])

    def test_route_pair_is_unique_in_api_and_database(self):
        response = self.client.post(self.endpoint("routes"), {
            "source": self.source.pk, "destination": self.destination.pk,
            "distance": 1,
        })
        self.assertEqual(response.status_code, 400)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Route.objects.create(
                source=self.source, destination=self.destination, distance=1,
            )

    def test_route_partial_update_rejects_existing_pair(self):
        other = Airport.objects.create(name="Schiphol", closest_big_city="AMS")
        route = Route.objects.create(
            source=self.source, destination=other, distance=50,
        )
        response = self.client.patch(self.endpoint("routes", route.pk), {
            "destination": self.destination.pk,
        })
        self.assertEqual(response.status_code, 400)
        route.refresh_from_db()
        self.assertEqual(route.destination, other)

    def test_model_save_trims_catalogue_names(self):
        airport = Airport.objects.create(
            name=" \tSchiphol\n ", closest_big_city="Amsterdam",
        )
        crew = Crew.objects.create(first_name=" Ada ", last_name=" Pilot ")
        airport.refresh_from_db()
        crew.refresh_from_db()
        self.assertEqual(airport.name, "Schiphol")
        self.assertEqual((crew.first_name, crew.last_name), ("Ada", "Pilot"))

    def test_model_save_rejects_whitespace_names(self):
        for model, values, field in (
            (Airport, {"name": " \t\n", "closest_big_city": "City"}, "name"),
            (Crew, {"first_name": "\t ", "last_name": "Pilot"}, "first_name"),
            (Crew, {"first_name": "Ada", "last_name": "\n "}, "last_name"),
        ):
            with self.subTest(model=model, field=field):
                with self.assertRaises(ValidationError) as error:
                    model.objects.create(**values)
                self.assertIn(field, error.exception.message_dict)

    def test_model_clean_trims_and_rejects_whitespace_names(self):
        airport = Airport(name="  Schiphol  ", closest_big_city="Amsterdam")
        airport.full_clean()
        self.assertEqual(airport.name, "Schiphol")
        crew = Crew(first_name=" ", last_name="Pilot")
        with self.assertRaises(ValidationError) as error:
            crew.full_clean()
        self.assertIn("first_name", error.exception.message_dict)

    def test_database_rejects_empty_catalogue_names(self):
        for queryset, values in (
            (Airport.objects.filter(pk=self.source.pk), {"name": " "}),
            (Crew.objects.filter(pk=self.crew.pk), {"first_name": " "}),
            (Crew.objects.filter(pk=self.crew.pk), {"last_name": ""}),
        ):
            with self.subTest(values=values):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    queryset.update(**values)

    def test_api_trims_names_and_rejects_whitespace(self):
        response = self.client.post(self.endpoint("airports"), {
            "name": "  Schiphol  ", "closest_big_city": "Amsterdam",
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["name"], "Schiphol")
        for resource, payload in (
            ("airports", {"name": " \t", "closest_big_city": "City"}),
            ("crew", {"first_name": " ", "last_name": "Pilot"}),
            ("crew", {"first_name": "Ada", "last_name": "\t"}),
        ):
            with self.subTest(resource=resource, payload=payload):
                response = self.client.post(self.endpoint(resource), payload)
                self.assertEqual(response.status_code, 400)

    def test_booked_airplane_type_is_readonly_in_admin(self):
        self.create_order()
        model_admin = AirplaneAdmin(Airplane, admin.site)
        fields = model_admin.get_readonly_fields(RequestFactory().get("/"),
                                                 self.airplane)
        self.assertIn("airplane_type", fields)

    def test_admin_form_rejects_booked_airplane_type_change(self):
        self.create_order()
        other = AirplaneType.objects.create(name="Boeing 737")
        form = AirplaneAdminForm(instance=self.airplane, data={
            "name": self.airplane.name, "rows": self.airplane.rows,
            "seats_in_row": self.airplane.seats_in_row,
            "airplane_type": other.pk,
        })
        self.assertFalse(form.is_valid())

    def test_user_deletion_preserves_orders_and_tickets(self):
        order = self.create_order()
        with self.assertRaises(ProtectedError):
            self.user.delete()
        self.assertTrue(Order.objects.filter(pk=order.pk).exists())
        self.assertEqual(order.tickets.count(), 1)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(order.tickets.count(), 1)

    def test_admin_user_delete_page_identifies_protected_booking(self):
        self.create_order()
        self.staff.is_superuser = True
        self.staff.save(update_fields=["is_superuser"])
        self.client.force_login(self.staff)
        response = self.client.get(reverse(
            "admin:user_user_delete", args=[self.user.pk],
        ))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["protected"])


class TicketRequestReviewTests(AirportAPITestCase):
    def test_is_valid_rejects_departed_flight(self):
        self.flight.departure_time = timezone.now() - timedelta(hours=2)
        self.flight.arrival_time = timezone.now() - timedelta(hours=1)
        self.flight.save()
        serializer = TicketRequestSerializer(data={
            "flight": self.flight.pk, "row": 1, "seat": 1,
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn("flight", serializer.errors)

    def test_is_valid_rejects_row_and_seat_outside_airplane(self):
        serializer = TicketRequestSerializer(data={
            "flight": self.flight.pk, "row": 5, "seat": 7,
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn("row", serializer.errors)
        self.assertIn("seat", serializer.errors)

    def test_hundred_tickets_are_accepted_and_101_rejected_for_all_users(self):
        self.airplane.rows = 101
        self.airplane.seats_in_row = 1
        self.airplane.save()
        for user in (self.user, self.staff):
            for count, expected in ((100, True), (101, False)):
                with self.subTest(staff=user.is_staff, count=count):
                    serializer = OrderCreateSerializer(data={"tickets": [
                        {"flight": self.flight.pk, "row": row, "seat": 1}
                        for row in range(1, count + 1)
                    ]}, context={"request": SimpleNamespace(user=user)})
                    self.assertEqual(serializer.is_valid(), expected)

    @override_settings(MAX_TICKETS_PER_ORDER=2)
    def test_ticket_limit_uses_setting_and_is_documented(self):
        serializer = OrderCreateSerializer(data={"tickets": [
            {"flight": self.flight.pk, "row": 1, "seat": seat}
            for seat in (1, 2, 3)
        ]})
        self.assertFalse(serializer.is_valid())
        self.assertEqual(serializer.fields["tickets"].max_length, 2)
        self.assertIn("2", str(serializer.fields["tickets"].help_text))

    @override_settings(MAX_TICKETS_PER_ORDER=2)
    def test_schema_exposes_ticket_array_limits_from_setting(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        tickets = schema["components"]["schemas"]["OrderCreateRequest"][
            "properties"
        ]["tickets"]
        self.assertEqual(tickets.get("maxItems"), 2)
        self.assertEqual(tickets.get("minItems"), 1)


class CatalogueMigrationReviewTests(TransactionTestCase):
    migrate_from = [("airport", "0001_initial")]
    migrate_to = [("airport", "0002_catalogue_validation")]

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        self.apps = executor.loader.project_state(self.migrate_from).apps
        self.airport_model = self.apps.get_model("airport", "Airport")
        self.route_model = self.apps.get_model("airport", "Route")
        self.crew_model = self.apps.get_model("airport", "Crew")

    def tearDown(self):
        for name in ("Ticket", "Order", "Flight", "Route", "Airplane",
                     "AirplaneType", "Crew", "Airport"):
            self.apps.get_model("airport", name).objects.all().delete()
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_migration_refuses_conflicts_and_preserves_bookings(self):
        source = self.airport_model.objects.create(
            name="Duplicate", closest_big_city="City",
        )
        self.airport_model.objects.create(
            name="Duplicate", closest_big_city="X",
        )
        destination = self.airport_model.objects.create(
            name=" Whitespace ", closest_big_city="City",
        )
        self.crew_model.objects.create(first_name="\t", last_name="Pilot")
        route = self.route_model.objects.create(
            source=source, destination=destination, distance=1,
        )
        self.route_model.objects.create(
            source=source, destination=destination, distance=2,
        )
        plane_type_model = self.apps.get_model("airport", "AirplaneType")
        plane_type = plane_type_model.objects.create(name="Airbus")
        plane = self.apps.get_model("airport", "Airplane").objects.create(
            name="Plane", rows=1, seats_in_row=1, airplane_type=plane_type,
        )
        flight = self.apps.get_model("airport", "Flight").objects.create(
            route=route, airplane=plane, departure_time=timezone.now(),
            arrival_time=timezone.now() + timedelta(hours=1),
        )
        user = self.apps.get_model("user", "User").objects.create(
            email="historical@example.com",
        )
        order_model = self.apps.get_model("airport", "Order")
        order = order_model.objects.create(user=user)
        ticket_model = self.apps.get_model("airport", "Ticket")
        ticket = ticket_model.objects.create(
            flight=flight, order=order, row=1, seat=1,
        )
        try:
            MigrationExecutor(connection).migrate(self.migrate_to)
        except Exception as error:
            self.assertIsInstance(error, RuntimeError)
            message = str(error)
        else:
            self.fail("Migration must refuse conflicting existing data.")
        for fragment in ("Airport", "Route", "Crew", "resolve", "unchanged"):
            self.assertIn(fragment, message)
        self.assertEqual(self.airport_model.objects.count(), 3)
        self.assertEqual(self.route_model.objects.count(), 2)
        self.assertTrue(ticket_model.objects.filter(
            pk=ticket.pk, order_id=order.pk, flight_id=flight.pk,
        ).exists())
