from django import forms
from django.contrib import admin
from rest_framework.exceptions import ValidationError as ApiValidationError

from airport.models import (
    Airplane,
    AirplaneType,
    Airport,
    Crew,
    Flight,
    Order,
    Route,
    Ticket,
)


class RouteAdminForm(forms.ModelForm):
    class Meta:
        model = Route
        fields = "__all__"

    def clean(self):
        data = super().clean()
        if self.instance.pk:
            current = Route.objects.select_for_update().get(
                pk=self.instance.pk
            )
            if current.flights.filter(tickets__isnull=False).exists() and any(
                field in data and data[field] != getattr(current, field)
                for field in ("source", "destination")
            ):
                raise forms.ValidationError(
                    "Cannot change the airports of a booked route."
                )
        return data


class AirplaneAdminForm(forms.ModelForm):
    class Meta:
        model = Airplane
        fields = "__all__"

    def clean(self):
        data = super().clean()
        if self.instance.pk:
            current = Airplane.objects.select_for_update().get(
                pk=self.instance.pk
            )
            if current.flights.filter(tickets__isnull=False).exists() and any(
                field in data and data[field] != getattr(current, field)
                for field in ("rows", "seats_in_row")
            ):
                raise forms.ValidationError(
                    "Cannot change the seating plan of a booked airplane."
                )
        return data


class FlightAdminForm(forms.ModelForm):
    class Meta:
        model = Flight
        fields = "__all__"

    def clean(self):
        from airport.services import validate_flight_schedule

        data = super().clean()
        instance = self.instance
        values = {
            field: data.get(field, getattr(instance, field, None))
            for field in (
                "route", "airplane", "departure_time", "arrival_time"
            )
        }
        if not all(values.values()):
            return data
        crew = list(data.get(
            "crew", instance.crew.all() if instance.pk else []
        ))
        # The admin change view wraps form validation and saving in atomic.
        # Match the API's route -> airplane -> crew -> flight lock order.
        list(Route.objects.select_for_update().filter(
            pk__in={instance.route_id, values["route"].pk}
        ).order_by("pk"))
        list(Airplane.objects.select_for_update().filter(
            pk__in={instance.airplane_id, values["airplane"].pk}
        ).order_by("pk"))
        list(Crew.objects.select_for_update().filter(
            pk__in=[member.pk for member in crew]
        ).order_by("pk"))
        if instance.pk:
            current = Flight.objects.select_for_update().get(pk=instance.pk)
            if any(
                getattr(current, field) != getattr(instance, field)
                for field in values
            ):
                raise forms.ValidationError(
                    "Flight changed. Reload the page and retry."
                )
            changed = any(
                value != getattr(current, field)
                for field, value in values.items()
            ) or {member.pk for member in crew} != set(
                current.crew.values_list("pk", flat=True)
            )
            if changed and current.tickets.exists():
                raise forms.ValidationError(
                    "Cannot change the schedule or crew of a booked flight."
                )
        try:
            validate_flight_schedule(
                airplane=values["airplane"], crew=crew,
                departure_time=values["departure_time"],
                arrival_time=values["arrival_time"],
                exclude_flight_id=instance.pk,
            )
        except ApiValidationError as error:
            raise forms.ValidationError({
                field if field in self.fields else "__all__": str(message)
                for field, message in error.detail.items()
            }) from error
        return data


@admin.register(Airport)
class AirportAdmin(admin.ModelAdmin):
    list_display = ("name", "closest_big_city")
    search_fields = ("name", "closest_big_city")


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    form = RouteAdminForm
    list_display = ("source", "destination", "distance")
    list_filter = ("source", "destination")
    search_fields = ("source__name", "destination__name")
    list_select_related = ("source", "destination")
    autocomplete_fields = ("source", "destination")

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.flights.filter(tickets__isnull=False).exists():
            return ("source", "destination")
        return ()


@admin.register(Crew)
class CrewAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name")
    search_fields = ("first_name", "last_name")


@admin.register(AirplaneType)
class AirplaneTypeAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Airplane)
class AirplaneAdmin(admin.ModelAdmin):
    form = AirplaneAdminForm
    list_display = (
        "name", "airplane_type", "rows", "seats_in_row", "capacity"
    )
    list_filter = ("airplane_type",)
    search_fields = ("name", "airplane_type__name")
    list_select_related = ("airplane_type",)
    autocomplete_fields = ("airplane_type",)

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.flights.filter(tickets__isnull=False).exists():
            return ("rows", "seats_in_row")
        return ()


@admin.register(Flight)
class FlightAdmin(admin.ModelAdmin):
    form = FlightAdminForm
    list_display = ("route", "airplane", "departure_time", "arrival_time")
    list_filter = ("departure_time", "route__source", "route__destination")
    search_fields = (
        "route__source__name",
        "route__destination__name",
        "airplane__name",
    )
    list_select_related = ("route__source", "route__destination", "airplane")
    autocomplete_fields = ("route", "airplane")
    filter_horizontal = ("crew",)
    date_hierarchy = "departure_time"

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.tickets.exists():
            return (
                "route", "airplane", "departure_time", "arrival_time", "crew"
            )
        return ()


class ReadOnlyBookingPermissions:
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class TicketInline(ReadOnlyBookingPermissions, admin.TabularInline):
    model = Ticket
    extra = 0
    can_delete = False
    readonly_fields = ("flight", "row", "seat")


@admin.register(Order)
class OrderAdmin(ReadOnlyBookingPermissions, admin.ModelAdmin):
    list_display = ("id", "user", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__email",)
    list_select_related = ("user",)
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at",)
    inlines = (TicketInline,)
    date_hierarchy = "created_at"


@admin.register(Ticket)
class TicketAdmin(ReadOnlyBookingPermissions, admin.ModelAdmin):
    list_display = ("id", "flight", "row", "seat", "order")
    list_filter = ("flight__departure_time",)
    search_fields = (
        "order__user__email",
        "flight__route__source__name",
        "flight__route__destination__name",
    )
    list_select_related = (
        "flight__route__source",
        "flight__route__destination",
        "order",
    )
    autocomplete_fields = ("flight", "order")
