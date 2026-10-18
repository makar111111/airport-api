from rest_framework import serializers


class AirportFilterSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, max_length=255)
    city = serializers.CharField(required=False, max_length=255)


class RouteFilterSerializer(serializers.Serializer):
    source = serializers.IntegerField(required=False, min_value=1)
    destination = serializers.IntegerField(required=False, min_value=1)


class AirplaneFilterSerializer(serializers.Serializer):
    airplane_type = serializers.IntegerField(required=False, min_value=1)


class FlightFilterSerializer(RouteFilterSerializer):
    date = serializers.DateField(required=False, input_formats=["%Y-%m-%d"])
    available = serializers.BooleanField(required=False)
    ordering = serializers.ChoiceField(
        required=False,
        choices=["departure_time", "-departure_time"],
        default="departure_time",
    )
