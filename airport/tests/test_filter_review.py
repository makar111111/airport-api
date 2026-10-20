from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from airport.models import Airplane, Airport, Crew, Flight, Route
from airport.tests.helpers import AirportAPITestCase


class CatalogueFilterReviewTests(AirportAPITestCase):
    def setUp(self):
        super().setUp()
        self.departure = datetime(2030, 1, 2, 12, tzinfo=timezone.utc)
        self.flight.departure_time = self.departure
        self.flight.arrival_time = self.departure + timedelta(hours=3)
        self.flight.save()

    def make_flight(self, *, departure=None, route=None, airplane=None):
        departure = departure or self.departure
        if airplane is None:
            airplane = Airplane.objects.create(
                name="Filter test airplane", rows=4, seats_in_row=6,
                airplane_type=self.airplane_type,
            )
        return Flight.objects.create(
            route=route or self.route,
            airplane=airplane,
            departure_time=departure,
            arrival_time=departure + timedelta(hours=1),
        )

    def result_ids(self, query=None):
        response = self.client.get(self.endpoint("flights"), query or {})
        self.assertEqual(response.status_code, 200, response.data)
        return [item["id"] for item in response.data["results"]]

    def sell_out(self, flight):
        airplane = Airplane.objects.create(
            name="One-seat airplane", rows=1, seats_in_row=1,
            airplane_type=self.airplane_type,
        )
        flight.airplane = airplane
        flight.save(update_fields=["airplane"])
        self.create_order(flight=flight)

    def test_repeated_supported_filter_parameters_are_rejected(self):
        cases = [
            ("airports", "name", "Boryspil"),
            ("airports", "city", "Kyiv"),
            ("routes", "source", self.source.pk),
            ("routes", "destination", self.destination.pk),
            ("airplanes", "airplane_type", self.airplane_type.pk),
            ("flights", "source", self.source.pk),
            ("flights", "destination", self.destination.pk),
            ("flights", "date", "2030-01-02"),
            ("flights", "available", "true"),
            ("flights", "ordering", "departure_time"),
        ]
        for resource, field, value in cases:
            with self.subTest(resource=resource, field=field):
                query = urlencode([(field, value), (field, value)])
                response = self.client.get(
                    f"{self.endpoint(resource)}?{query}"
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)

    def test_repeated_different_filter_values_are_rejected(self):
        response = self.client.get(
            f"{self.endpoint('flights')}?available=false&available=true"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("available", response.data)

    def test_unknown_parameters_and_pagination_are_allowed(self):
        response = self.client.get(
            f"{self.endpoint('flights')}?page=1&unused=one&unused=two"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_omitted_available_includes_free_and_sold_out_flights(self):
        self.sell_out(self.flight)
        free_flight = self.make_flight(
            departure=self.departure + timedelta(hours=5)
        )
        self.assertEqual(self.result_ids(), [self.flight.pk, free_flight.pk])

    def test_available_selects_free_or_sold_out_flights(self):
        self.sell_out(self.flight)
        free_flight = self.make_flight(
            departure=self.departure + timedelta(hours=5)
        )
        for value, expected in (
            ("true", [free_flight.pk]), ("false", [self.flight.pk]),
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    self.result_ids({"available": value}), expected
                )

    def test_invalid_and_impossible_dates_return_field_errors(self):
        for value in (
            "tomorrow", "2030-02-30", "2030-13-01", "2030-01-00",
            "02/01/2030", "",
        ):
            with self.subTest(value=value):
                response = self.client.get(
                    self.endpoint("flights"), {"date": value}
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("date", response.data)

    def test_invalid_booleans_return_field_errors(self):
        for value in ("perhaps", "2", "null", ""):
            with self.subTest(value=value):
                response = self.client.get(
                    self.endpoint("flights"), {"available": value}
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("available", response.data)

    def test_unsupported_ordering_returns_field_errors(self):
        for value in (
            "id", "-id", "arrival_time", "departure_time,id", "",
        ):
            with self.subTest(value=value):
                response = self.client.get(
                    self.endpoint("flights"), {"ordering": value}
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("ordering", response.data)

    def test_nonexistent_airports_return_empty_route_and_flight_lists(self):
        for resource in ("routes", "flights"):
            for field in ("source", "destination"):
                with self.subTest(resource=resource, field=field):
                    response = self.client.get(
                        self.endpoint(resource), {field: 999999}
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.data["count"], 0)
                    self.assertEqual(response.data["results"], [])

    def test_all_flight_filters_combine_without_duplicate_results(self):
        later = self.make_flight(
            departure=self.departure + timedelta(hours=2)
        )
        self.make_flight(departure=self.departure + timedelta(days=1))
        sold_out = self.make_flight()
        self.sell_out(sold_out)
        other = Airport.objects.create(
            name="Other airport", closest_big_city="Other city"
        )
        for source, destination in (
            (other, self.destination), (self.source, other),
        ):
            route = Route.objects.create(
                source=source, destination=destination, distance=500
            )
            self.make_flight(route=route)
        self.flight.crew.add(Crew.objects.create(
            first_name="Grace", last_name="Pilot"
        ))
        self.create_order(flight=self.flight, seat=1)
        self.create_order(flight=self.flight, seat=2)

        self.assertEqual(self.result_ids({
            "source": self.source.pk,
            "destination": self.destination.pk,
            "date": "2030-01-02",
            "available": "true",
            "ordering": "-departure_time",
        }), [later.pk, self.flight.pk])

    def test_date_filter_uses_the_utc_departure_day(self):
        previous_day = self.make_flight(departure=datetime(
            2030, 1, 2, 0, 30,
            tzinfo=timezone(timedelta(hours=3)),
        ))
        next_day = self.make_flight(departure=datetime(
            2030, 1, 2, 23, 30,
            tzinfo=timezone(timedelta(hours=-3)),
        ))
        for day, expected in (
            ("2030-01-01", [previous_day.pk]),
            ("2030-01-02", [self.flight.pk]),
            ("2030-01-03", [next_day.pk]),
        ):
            with self.subTest(day=day):
                self.assertEqual(self.result_ids({"date": day}), expected)

    def test_departure_time_ties_use_ascending_ids_in_both_orders(self):
        same_time = [self.flight, self.make_flight(), self.make_flight()]
        earlier = self.make_flight(
            departure=self.departure - timedelta(hours=3)
        )
        ties = [flight.pk for flight in same_time]
        for ordering, expected in (
            ("departure_time", [earlier.pk, *ties]),
            ("-departure_time", [*ties, earlier.pk]),
        ):
            with self.subTest(ordering=ordering):
                self.assertEqual(
                    self.result_ids({"ordering": ordering}), expected
                )
