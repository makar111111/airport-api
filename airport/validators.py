"""Validation shared by model writes, serializers and the admin."""

from django import forms
from django.core.exceptions import ValidationError
from PIL import Image


MAX_AIRPLANE_IMAGE_BYTES = 5 * 1024 * 1024


def airplane_image_extension(value):
    """Validate image content and return its canonical, detected extension.

    Pillow may seek while checking the file; leave the caller's stream at the
    same position, including on invalid uploads.
    """
    if value.size > MAX_AIRPLANE_IMAGE_BYTES:
        raise ValidationError(
            "Image must be at most 5 MiB.", code="image_size"
        )
    position = value.tell()
    try:
        value.seek(0)
        image = Image.open(value)
        image_format = image.format
        image.verify()
        extensions = {
            "JPEG": ".jpg", "PNG": ".png", "GIF": ".gif",
            "TIFF": ".tiff", "WEBP": ".webp", "BMP": ".bmp",
        }
        extension = extensions.get(image_format)
        if extension is None:
            extension = next((
                suffix for suffix, format_name in Image.registered_extensions()
                .items() if format_name == image_format
            ), None)
        if extension is None:
            raise ValueError("Unsupported image format.")
        return extension
    except (
        OSError, SyntaxError, ValueError, Image.DecompressionBombError
    ) as e:
        raise ValidationError(
            "Upload a valid image. The file is invalid or corrupted.",
            code="invalid_image",
        ) from e
    finally:
        value.seek(position)


def validate_airplane_image(value):
    airplane_image_extension(value)


class AirplaneImageFormField(forms.FileField):
    """Check actual file content without trusting the supplied filename."""

    default_validators = [validate_airplane_image]
