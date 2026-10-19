import uuid
from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.fields.files import ImageFieldFile
from django.utils import timezone

from airport.validators import (
    airplane_image_extension,
    validate_airplane_image,
)


def _trim_required_names(instance, field_names):
    errors = {}
    for field in field_names:
        value = getattr(instance, field)
        if isinstance(value, str):
            value = value.strip()
            setattr(instance, field, value)
            if not value:
                errors[field] = "This field cannot be blank."
    if errors:
        raise ValidationError(errors)


def airplane_image_file_path(instance, filename):
    extension = airplane_image_extension(instance.image)
    return f"uploads/airplanes/{uuid.uuid4()}{extension}"


class AirplaneImageFieldFile(ImageFieldFile):
    def save(self, name, content, save=True):
        # Direct image.save() and bulk_create() also pass through this method.
        validate_airplane_image(content)
        self.file = content
        self._committed = False
        setattr(self.instance, self.field.attname, self)
        return super().save(name, content, save=save)


class AirplaneImageField(models.ImageField):
    attr_class = AirplaneImageFieldFile


class Airport(models.Model):
    name = models.CharField(max_length=255, unique=True)
    closest_big_city = models.CharField(max_length=255)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(name__regex=r"^\s*$"),
                name="airport_name_not_blank",
            ),
        ]

    def clean(self):
        super().clean()
        _trim_required_names(self, ("name",))

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Route(models.Model):
    source = models.ForeignKey(
        Airport, on_delete=models.PROTECT, related_name="departures"
    )
    destination = models.ForeignKey(
        Airport, on_delete=models.PROTECT, related_name="arrivals"
    )
    distance = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        ordering = ["source__name", "destination__name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "destination"], name="unique_route_airports",
            ),
            models.CheckConstraint(
                condition=models.Q(distance__gt=0),
                name="route_distance_positive",
            ),
            models.CheckConstraint(
                condition=~models.Q(source=models.F("destination")),
                name="route_different_airports",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.source_id is not None
            and self.destination_id is not None
            and self.source_id == self.destination_id
        ):
            raise ValidationError(
                {"destination": "Source and destination must be different."}
            )

    def __str__(self):
        return f"{self.source} - {self.destination}"


class Crew(models.Model):
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)

    class Meta:
        ordering = ["last_name", "first_name", "id"]
        verbose_name_plural = "crew"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(first_name__regex=r"^\s*$"),
                name="crew_first_name_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(last_name__regex=r"^\s*$"),
                name="crew_last_name_not_blank",
            ),
        ]

    def clean(self):
        super().clean()
        _trim_required_names(self, ("first_name", "last_name"))

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return self.full_name


class AirplaneType(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class Airplane(models.Model):
    name = models.CharField(max_length=255)
    rows = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    seats_in_row = models.PositiveIntegerField(
        validators=[MinValueValidator(1)]
    )
    airplane_type = models.ForeignKey(
        AirplaneType, on_delete=models.PROTECT, related_name="airplanes"
    )
    image = AirplaneImageField(
        upload_to=airplane_image_file_path, blank=True,
        validators=[validate_airplane_image],
    )

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rows__gt=0), name="airplane_rows_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(seats_in_row__gt=0),
                name="airplane_seats_in_row_positive",
            ),
        ]

    @property
    def capacity(self):
        return self.rows * self.seats_in_row

    def save(self, *args, **kwargs):
        if self.image and not self.image._committed:
            validate_airplane_image(self.image)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Flight(models.Model):
    route = models.ForeignKey(
        Route, on_delete=models.PROTECT, related_name="flights"
    )
    airplane = models.ForeignKey(
        Airplane, on_delete=models.PROTECT, related_name="flights"
    )
    crew = models.ManyToManyField(Crew, related_name="flights", blank=True)
    departure_time = models.DateTimeField()
    arrival_time = models.DateTimeField()

    class Meta:
        ordering = ["departure_time", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    arrival_time__gt=models.F("departure_time")
                ),
                name="flight_arrival_after_departure",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        for field_name in ("departure_time", "arrival_time"):
            value = getattr(self, field_name)
            if isinstance(value, datetime) and timezone.is_naive(value):
                errors[field_name] = "Use a timezone-aware date and time."
        if (
            not errors
            and isinstance(self.departure_time, datetime)
            and isinstance(self.arrival_time, datetime)
            and self.arrival_time <= self.departure_time
        ):
            errors["arrival_time"] = "Arrival must be after departure."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.route} ({self.departure_time})"


class Order(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Order {self.pk}"


class Ticket(models.Model):
    row = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    seat = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    flight = models.ForeignKey(
        Flight, on_delete=models.PROTECT, related_name="tickets"
    )
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="tickets"
    )

    class Meta:
        ordering = ["row", "seat"]
        constraints = [
            models.UniqueConstraint(
                fields=["flight", "row", "seat"],
                name="unique_flight_seat",
            ),
            models.CheckConstraint(
                condition=models.Q(row__gt=0), name="ticket_row_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(seat__gt=0), name="ticket_seat_positive"
            ),
        ]

    def clean(self):
        super().clean()
        if self.flight_id is None:
            return
        try:
            airplane = self.flight.airplane
        except (
            Flight.DoesNotExist,
            Airplane.DoesNotExist,
            ValueError,
            TypeError,
        ):
            return
        errors = {}
        for field_name, maximum in (
            ("row", airplane.rows),
            ("seat", airplane.seats_in_row),
        ):
            value = getattr(self, field_name)
            if isinstance(value, int) and not 1 <= value <= maximum:
                errors[field_name] = f"Must be between 1 and {maximum}."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Flight {self.flight_id}: row {self.row}, seat {self.seat}"
