from django.test import SimpleTestCase
from rest_framework.test import APIClient


class EndpointContractTests(SimpleTestCase):
    def test_anonymous_flight_list_returns_authentication_error(self):
        response = APIClient().get("/api/airport/flights/")
        self.assertEqual(response.status_code, 401)
