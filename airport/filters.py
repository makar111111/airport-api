"""Scalar query filters: every supported parameter accepts exactly one value.

Repeated supported parameters return HTTP 400; unknown query parameters are
ignored here so pagination and other independent API options keep working.
"""

from rest_framework import serializers


SINGLE_VALUE_HELP = "Provide one value; repeated parameters return HTTP 400."


class AirportFilterSerializer(serializers.Serializer):
    name = serializers.CharField(
        required=False, max_length=255,
        help_text=f"Case-insensitive airport name match. {SINGLE_VALUE_HELP}",
    )
    city = serializers.CharField(
        required=False, max_length=255,
        help_text=f"Case-insensitive nearest city match. {SINGLE_VALUE_HELP}",
    )


class RouteFilterSerializer(serializers.Serializer):
    source = serializers.IntegerField(
        required=False, min_value=1,
        help_text=f"Source airport ID. {SINGLE_VALUE_HELP}",
    )
    destination = serializers.IntegerField(
        required=False, min_value=1,
        help_text=f"Destination airport ID. {SINGLE_VALUE_HELP}",
    )


class AirplaneFilterSerializer(serializers.Serializer):
    airplane_type = serializers.IntegerField(
        required=False, min_value=1,
        help_text=f"Airplane type ID. {SINGLE_VALUE_HELP}",
    )


class FlightFilterSerializer(RouteFilterSerializer):
    date = serializers.DateField(
        required=False, input_formats=["%Y-%m-%d"],
        help_text=f"UTC departure date (YYYY-MM-DD). {SINGLE_VALUE_HELP}",
    )
    available = serializers.BooleanField(
        required=False,
        help_text=(
            "true selects flights with free seats; false selects sold-out "
            "flights. Omit to include both. " + SINGLE_VALUE_HELP
        ),
    )
    ordering = serializers.ChoiceField(
        required=False,
        choices=["departure_time", "-departure_time"],
        default="departure_time",
        help_text=(
            "Departure time ascending or descending; equal departure times "
            "always use ascending IDs. " + SINGLE_VALUE_HELP
        ),
    )
