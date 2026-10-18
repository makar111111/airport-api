import io
import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework.exceptions import ValidationError

from airport.models import Airplane, Airport, Flight
from airport.serializers import AirplaneImageSerializer, RouteSerializer
from airport.tests.helpers import AirportAPITestCase


class CatalogueTests(AirportAPITestCase):
    def test_anonymous_catalogue_requires_authentication(self):
        self.client.force_authenticate(None)
        response = self.client.get(self.endpoint("flights"))
        self.assertEqual(response.status_code, 401)

    def test_authenticated_user_can_read_all_catalogue_resources(self):
        for resource in (
            "airports", "routes", "crew", "airplane-types", "airplanes",
            "flights",
        ):
            with self.subTest(resource=resource):
                response = self.client.get(self.endpoint(resource))
                self.assertEqual(response.status_code, 200)
                self.assertIn("results", response.data)

    def test_regular_user_cannot_write_catalogue(self):
        response = self.client.post(
            self.endpoint("airports"),
            {"name": "Luton", "closest_big_city": "London"},
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.patch(
            self.endpoint("airplanes", self.airplane.pk), {"rows": 9}
        )
        self.assertEqual(response.status_code, 403)

    def test_staff_can_create_update_and_delete_unused_airport(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(
            self.endpoint("airports"),
            {"name": "Luton", "closest_big_city": "London"},
        )
        self.assertEqual(response.status_code, 201)
        url = self.endpoint("airports", response.data["id"])
        self.assertEqual(
            self.client.patch(url, {"name": "London Luton"}).status_code, 200
        )
        self.assertEqual(self.client.delete(url).status_code, 204)

    def test_referenced_catalogue_delete_is_validation_error(self):
        self.client.force_authenticate(self.staff)
        response = self.client.delete(
            self.endpoint("airports", self.source.pk)
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Airport.objects.filter(pk=self.source.pk).exists())

    def test_invalid_route_and_airplane_dimensions_are_rejected(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(
            self.endpoint("routes"),
            {"source": self.source.pk, "destination": self.source.pk,
             "distance": 10},
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.patch(
            self.endpoint("airplanes", self.airplane.pk), {"rows": 0}
        )
        self.assertEqual(response.status_code, 400)

    def test_route_update_revalidates_airports_after_concurrent_change(self):
        other = Airport.objects.create(
            name="Schiphol", closest_big_city="Amsterdam"
        )
        serializer = RouteSerializer(
            self.route, data={"destination": other.pk}, partial=True
        )
        serializer.is_valid(raise_exception=True)
        type(self.route).objects.filter(pk=self.route.pk).update(source=other)
        with self.assertRaises(Exception) as result:
            serializer.save()
        self.assertIsInstance(result.exception, ValidationError)
        self.route.refresh_from_db()
        self.assertEqual(self.route.destination, self.destination)

    def test_filters_match_city_route_airplane_type_and_departure_date(self):
        cases = [
            ("airports", {"city": "kyiv"}, self.source.pk),
            ("airports", {"name": "Heath"}, self.destination.pk),
            ("routes", {"source": self.source.pk}, self.route.pk),
            ("airplanes", {"airplane_type": self.airplane_type.pk},
             self.airplane.pk),
            ("flights", {"source": self.source.pk,
                         "destination": self.destination.pk,
                         "date": self.departure.date().isoformat()},
             self.flight.pk),
        ]
        for resource, query, expected_id in cases:
            with self.subTest(resource=resource):
                response = self.client.get(self.endpoint(resource), query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [item["id"] for item in response.data["results"]],
                    [expected_id],
                )

    def test_malformed_filters_return_400(self):
        cases = [
            ("routes", {"source": "NaN"}),
            ("routes", {"destination": "-1"}),
            ("airplanes", {"airplane_type": "abc"}),
            ("flights", {"date": "tomorrow"}),
            ("flights", {"available": "perhaps"}),
            ("flights", {"source": "1,2"}),
            ("flights", {"ordering": "unknown"}),
        ]
        for resource, query in cases:
            with self.subTest(query=query):
                response = self.client.get(self.endpoint(resource), query)
                self.assertEqual(response.status_code, 400)

    def test_flight_list_and_detail_show_capacity_and_taken_places(self):
        self.create_order(row=2, seat=4)
        response = self.client.get(self.endpoint("flights"))
        item = response.data["results"][0]
        self.assertEqual(item["capacity"], 24)
        self.assertEqual(item["tickets_available"], 23)
        self.assertIn("source", item["route"])
        response = self.client.get(self.endpoint("flights", self.flight.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["taken_places"], [{"row": 2, "seat": 4}]
        )
        self.assertEqual(response.data["crew"][0]["full_name"], "Ada Pilot")

    def test_full_flight_is_excluded_by_available_filter(self):
        self.airplane.rows = 1
        self.airplane.seats_in_row = 1
        self.airplane.save()
        self.create_order()
        response = self.client.get(
            self.endpoint("flights"), {"available": "true"}
        )
        self.assertEqual(response.data["count"], 0)

    def test_flights_default_order_is_departure_time(self):
        earlier = Flight.objects.create(
            route=self.route, airplane=self.airplane,
            departure_time=self.departure - timedelta(hours=8),
            arrival_time=self.departure - timedelta(hours=5),
        )
        response = self.client.get(self.endpoint("flights"))
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [earlier.pk, self.flight.pk],
        )


class FlightSchedulingTests(AirportAPITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.staff)

    def test_staff_creates_flight_with_crew(self):
        response = self.client.post(
            self.endpoint("flights"), self.flight_payload()
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            list(Flight.objects.get(pk=response.data["id"]).crew.all()),
            [self.crew],
        )

    def test_airplane_schedule_overlap_is_rejected(self):
        response = self.client.post(
            self.endpoint("flights"),
            self.flight_payload(
                crew=[], departure_time=self.departure.isoformat(),
                arrival_time=(self.departure + timedelta(hours=2)).isoformat(),
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Flight.objects.count(), 1)

    def test_crew_schedule_overlap_on_different_airplane_is_rejected(self):
        another = Airplane.objects.create(
            name="UR-SECOND", rows=3, seats_in_row=4,
            airplane_type=self.airplane_type,
        )
        response = self.client.post(
            self.endpoint("flights"),
            self.flight_payload(
                airplane=another.pk,
                departure_time=self.departure.isoformat(),
                arrival_time=(self.departure + timedelta(hours=2)).isoformat(),
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Flight.objects.count(), 1)

    def test_touching_flight_times_are_allowed(self):
        start = self.flight.arrival_time
        response = self.client.post(
            self.endpoint("flights"),
            self.flight_payload(
                departure_time=start.isoformat(),
                arrival_time=(start + timedelta(hours=2)).isoformat(),
            ),
        )
        self.assertEqual(response.status_code, 201)

    def test_arrival_before_departure_is_rejected(self):
        response = self.client.post(
            self.endpoint("flights"),
            self.flight_payload(arrival_time=self.departure.isoformat()),
        )
        self.assertEqual(response.status_code, 400)

    def test_booked_flight_time_and_airplane_dimensions_are_protected(self):
        self.create_order()
        response = self.client.patch(
            self.endpoint("flights", self.flight.pk),
            {"departure_time": (
                self.departure + timedelta(minutes=30)
            ).isoformat()},
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.patch(
            self.endpoint("airplanes", self.airplane.pk), {"rows": 10}
        )
        self.assertEqual(response.status_code, 400)
        self.airplane.refresh_from_db()
        self.assertEqual(self.airplane.rows, 4)

    def test_booked_route_airports_are_protected(self):
        self.create_order()
        other = Airport.objects.create(
            name="Schiphol", closest_big_city="Amsterdam"
        )
        response = self.client.patch(
            self.endpoint("routes", self.route.pk), {"destination": other.pk}
        )
        self.assertEqual(response.status_code, 400)
        self.route.refresh_from_db()
        self.assertEqual(self.route.destination, self.destination)


class AirplaneImageTests(AirportAPITestCase):
    def setUp(self):
        super().setUp()
        self.media_dir = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_dir)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_dir)
        self.url = (
            self.endpoint("airplanes", self.airplane.pk) + "upload-image/"
        )

    @staticmethod
    def image_file():
        stream = io.BytesIO()
        Image.new("RGB", (10, 10), "blue").save(stream, format="PNG")
        return SimpleUploadedFile(
            "airplane.png", stream.getvalue(), content_type="image/png"
        )

    def test_regular_user_cannot_upload_image(self):
        response = self.client.post(
            self.url, {"image": self.image_file()}, format="multipart"
        )
        self.assertEqual(response.status_code, 403)

    def test_staff_can_upload_image_and_invalid_file_is_rejected(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(
            self.url, {"image": self.image_file()}, format="multipart"
        )
        self.assertEqual(response.status_code, 200)
        self.airplane.refresh_from_db()
        self.assertTrue(self.airplane.image.name.endswith(".png"))
        response = self.client.post(
            self.url,
            {"image": SimpleUploadedFile("fake.png", b"not an image")},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)

    def test_regular_airplane_update_does_not_accept_image(self):
        self.client.force_authenticate(self.staff)
        response = self.client.patch(
            self.endpoint("airplanes", self.airplane.pk),
            {"image": self.image_file()}, format="multipart",
        )
        self.assertEqual(response.status_code, 200)
        self.airplane.refresh_from_db()
        self.assertFalse(self.airplane.image)

    def test_image_larger_than_five_mib_is_rejected(self):
        self.client.force_authenticate(self.staff)
        original = self.image_file().read()
        oversized = original + b"\0" * (5 * 1024 * 1024 + 1 - len(original))
        response = self.client.post(
            self.url,
            {"image": SimpleUploadedFile(
                "large.png", oversized, content_type="image/png"
            )},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)
        self.airplane.refresh_from_db()
        self.assertFalse(self.airplane.image)

    def test_image_update_preserves_concurrent_airplane_changes(self):
        stale_airplane = Airplane.objects.get(pk=self.airplane.pk)
        Airplane.objects.filter(pk=self.airplane.pk).update(
            rows=5, name="Updated airplane"
        )
        serializer = AirplaneImageSerializer(
            stale_airplane, data={"image": self.image_file()}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        self.airplane.refresh_from_db()
        self.assertEqual(self.airplane.rows, 5)
        self.assertEqual(self.airplane.name, "Updated airplane")
