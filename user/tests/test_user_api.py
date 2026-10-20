from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from drf_spectacular.generators import SchemaGenerator
from rest_framework import status
from rest_framework.test import APIClient


PASSWORD = "FlightBooking!5937"


@override_settings(ROOT_URLCONF="user.tests.urls")
class PublicUserApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.register_url = reverse("user:register")
        self.token_url = reverse("user:token_obtain_pair")

    def test_register_normalizes_email_and_hashes_password(self):
        response = self.client.post(
            self.register_url,
            {"email": " Pilot@EXAMPLE.com ", "password": PASSWORD},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = get_user_model().objects.get()
        self.assertEqual(user.email, "pilot@example.com")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotEqual(user.password, PASSWORD)
        self.assertNotIn("password", response.data)

    def test_registration_cannot_grant_staff_status(self):
        response = self.client.post(
            self.register_url,
            {"email": "pilot@example.com", "password": PASSWORD,
             "is_staff": True},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(get_user_model().objects.get().is_staff)

    def test_duplicate_normalized_email_returns_400(self):
        get_user_model().objects.create_user("pilot@example.com", PASSWORD)
        response = self.client.post(
            self.register_url,
            {"email": "PILOT@EXAMPLE.COM", "password": PASSWORD},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_registration_rejects_weak_passwords(self):
        for password in ("short", "password", "123456789012"):
            with self.subTest(password=password):
                response = self.client.post(
                    self.register_url,
                    {"email": "pilot@example.com", "password": password},
                )
                self.assertEqual(
                    response.status_code, status.HTTP_400_BAD_REQUEST
                )
                self.assertIn("password", response.data)
        self.assertFalse(get_user_model().objects.exists())

    def test_registration_rejects_invalid_email(self):
        response = self.client.post(
            self.register_url, {"email": "invalid", "password": PASSWORD}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(get_user_model().objects.exists())

    def test_login_accepts_mixed_case_email_and_returns_real_jwt(self):
        get_user_model().objects.create_user("pilot@example.com", PASSWORD)
        response = self.client.post(
            self.token_url,
            {"email": "PILOT@Example.COM", "password": PASSWORD},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {response.data['access']}"
        )
        profile = self.client.get(reverse("user:manage"))
        self.assertEqual(profile.status_code, status.HTTP_200_OK)
        self.assertEqual(profile.data["email"], "pilot@example.com")

    def test_refresh_and_verify_jwt(self):
        get_user_model().objects.create_user("pilot@example.com", PASSWORD)
        tokens = self.client.post(
            self.token_url,
            {"email": "pilot@example.com", "password": PASSWORD},
        ).data
        response = self.client.post(
            reverse("user:token_refresh"), {"refresh": tokens["refresh"]}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        verified = self.client.post(
            reverse("user:token_verify"), {"token": response.data["access"]}
        )
        self.assertEqual(verified.status_code, status.HTTP_200_OK)

    def test_wrong_password_returns_401(self):
        get_user_model().objects.create_user("pilot@example.com", PASSWORD)
        response = self.client.post(
            self.token_url,
            {"email": "pilot@example.com", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_inactive_user_cannot_login(self):
        get_user_model().objects.create_user(
            "pilot@example.com", PASSWORD, is_active=False
        )
        response = self.client.post(
            self.token_url,
            {"email": "pilot@example.com", "password": PASSWORD},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_requires_authentication(self):
        response = self.client.get(reverse("user:manage"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_token_schema_documents_access_and_refresh_response(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        response = schema["paths"]["/api/user/token/"]["post"]["responses"]
        self.assertIn("content", response["200"])
        result = response["200"]["content"]["application/json"]["schema"]
        component = result["$ref"].rsplit("/", 1)[1]
        properties = schema["components"]["schemas"][component]["properties"]
        self.assertEqual(set(properties), {"access", "refresh"})


@override_settings(ROOT_URLCONF="user.tests.urls")
class PrivateUserApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            "pilot@example.com", PASSWORD
        )
        self.client.force_authenticate(self.user)
        self.url = reverse("user:manage")

    def test_profile_contains_only_current_user(self):
        get_user_model().objects.create_user("other@example.com", PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.user.pk)
        self.assertNotIn("password", response.data)

    def test_patch_email_normalizes_without_escalating_staff(self):
        response = self.client.patch(
            self.url, {"email": "NEW@EXAMPLE.COM", "is_staff": True}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")
        self.assertFalse(self.user.is_staff)

    def test_patch_password_uses_secure_hash(self):
        new_password = "UpdatedBooking!7251"
        response = self.client.patch(self.url, {"password": new_password})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))
        self.assertFalse(self.user.check_password(PASSWORD))
        self.assertNotIn("password", response.data)

    def test_patch_rejects_weak_password_and_preserves_existing(self):
        response = self.client.patch(self.url, {"password": "short"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_patch_rejects_other_users_normalized_email(self):
        get_user_model().objects.create_user("other@example.com", PASSWORD)
        response = self.client.patch(
            self.url, {"email": "OTHER@EXAMPLE.COM"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "pilot@example.com")

    def test_session_authentication_is_supported(self):
        self.client.force_authenticate(user=None)
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.user.pk)


class UserManagerTests(TestCase):
    def test_create_user_normalizes_full_email(self):
        user = get_user_model().objects.create_user(
            " PILOT@Example.COM ", PASSWORD
        )
        self.assertEqual(user.email, "pilot@example.com")
        self.assertTrue(user.check_password(PASSWORD))

    def test_user_requires_email(self):
        with self.assertRaises(ValueError):
            get_user_model().objects.create_user("", PASSWORD)

    def test_superuser_has_required_permissions(self):
        user = get_user_model().objects.create_superuser(
            "ADMIN@EXAMPLE.COM", PASSWORD
        )
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.email, "admin@example.com")

    def test_superuser_rejects_invalid_permission_flags(self):
        for flags in ({"is_staff": False}, {"is_superuser": False}):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                get_user_model().objects.create_superuser(
                    "admin@example.com", PASSWORD, **flags
                )

    def test_admin_add_form_hashes_password(self):
        from user.forms import UserCreationForm

        form = UserCreationForm(data={
            "email": "ADMIN@EXAMPLE.COM",
            "password1": PASSWORD,
            "password2": PASSWORD,
        })
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.email, "admin@example.com")
        self.assertTrue(user.check_password(PASSWORD))
