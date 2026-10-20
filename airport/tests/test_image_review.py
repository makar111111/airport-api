import io
import shutil
import tempfile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from airport.admin import AirplaneAdminForm
from airport.serializers import AirplaneImageSerializer
from airport.tests.helpers import AirportAPITestCase


class ImageReviewTests(AirportAPITestCase):
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
        self.client.force_authenticate(self.staff)

    @staticmethod
    def image_file(name="airplane.png", size=None):
        stream = io.BytesIO()
        Image.new("RGB", (10, 10), "blue").save(stream, format="PNG")
        content = stream.getvalue()
        if size:
            content += b"\0" * (size - len(content))
        return SimpleUploadedFile(name, content, content_type="image/png")

    def test_api_uses_detected_png_extension_for_disguised_images(self):
        for filename in ("airplane.jpg", "airplane.exe"):
            with self.subTest(filename=filename):
                response = self.client.post(self.url, {
                    "image": self.image_file(filename),
                }, format="multipart")
                self.assertEqual(response.status_code, 200)
                self.airplane.refresh_from_db()
                self.assertTrue(self.airplane.image.name.endswith(".png"))
                with Image.open(self.airplane.image) as image:
                    self.assertEqual(image.format, "PNG")
                self.airplane.image.close()

    def test_model_save_rejects_oversized_image(self):
        self.airplane.image = self.image_file(size=5 * 1024 * 1024 + 1)
        with self.assertRaises(ValidationError) as error:
            self.airplane.save()
        self.assertIn("5 MiB", str(error.exception))
        self.airplane.refresh_from_db()
        self.assertFalse(self.airplane.image)

    def test_modelform_rejects_oversized_image(self):
        form = AirplaneAdminForm(instance=self.airplane, data={
            "name": self.airplane.name, "rows": self.airplane.rows,
            "seats_in_row": self.airplane.seats_in_row,
            "airplane_type": self.airplane_type.pk,
        }, files={"image": self.image_file(size=5 * 1024 * 1024 + 1)})
        self.assertFalse(form.is_valid())
        self.assertIn("5 MiB", str(form.errors["image"]))

    def test_model_field_validator_rejects_oversized_image(self):
        self.airplane.image = self.image_file(size=5 * 1024 * 1024 + 1)
        with self.assertRaises(ValidationError) as error:
            self.airplane.full_clean()
        self.assertIn("image", error.exception.message_dict)

    def test_model_save_detects_extension_and_checks_corruption(self):
        self.airplane.image = self.image_file("disguised.exe")
        self.airplane.save()
        self.assertTrue(self.airplane.image.name.endswith(".png"))
        self.airplane.image = SimpleUploadedFile("fake.png", b"not an image")
        with self.assertRaises(ValidationError) as error:
            self.airplane.save()
        self.assertIn("valid image", str(error.exception))

    def test_validator_preserves_file_position(self):
        image = self.image_file()
        image.seek(7)
        self.airplane.image = image
        self.airplane.full_clean()
        self.assertEqual(image.tell(), 7)

    def test_serializer_accepts_exactly_five_mib(self):
        serializer = AirplaneImageSerializer(self.airplane, data={
            "image": self.image_file(size=5 * 1024 * 1024),
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_direct_field_save_rejects_oversized_image(self):
        with self.assertRaises(ValidationError):
            self.airplane.image.save(
                "large.png", self.image_file(size=5 * 1024 * 1024 + 1),
                save=False,
            )
