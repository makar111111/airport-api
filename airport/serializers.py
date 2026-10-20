from django.conf import settings
from django.core.validators import MaxLengthValidator, MinLengthValidator
from django.utils import timezone
from rest_framework import serializers

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
from airport.services import (
    reserve_order,
    save_flight,
    update_airplane,
    update_route,
)
from airport.validators import AirplaneImageFormField


class AirportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Airport
        fields = ["id", "name", "closest_big_city"]


class RouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Route
        fields = ["id", "source", "destination", "distance"]

    def validate(self, attrs):
        source = attrs.get("source", getattr(self.instance, "source", None))
        destination = attrs.get(
            "destination", getattr(self.instance, "destination", None)
        )
        if source == destination:
            raise serializers.ValidationError({
                "destination": "Source and destination must be different."
            })
        return attrs

    def update(self, instance, validated_data):
        return update_route(instance=instance, data=validated_data)


class RouteReadSerializer(RouteSerializer):
    source = AirportSerializer(read_only=True)
    destination = AirportSerializer(read_only=True)


class CrewSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Crew
        fields = ["id", "first_name", "last_name", "full_name"]


class AirplaneTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AirplaneType
        fields = ["id", "name"]


class AirplaneSerializer(serializers.ModelSerializer):
    capacity = serializers.IntegerField(read_only=True)
    airplane_type_name = serializers.CharField(
        source="airplane_type.name", read_only=True
    )

    class Meta:
        model = Airplane
        fields = [
            "id", "name", "rows", "seats_in_row", "capacity",
            "airplane_type", "airplane_type_name", "image",
        ]
        read_only_fields = ["image"]

    def update(self, instance, validated_data):
        return update_airplane(instance=instance, data=validated_data)


class AirplaneImageSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(
        required=True, allow_empty_file=False,
        _DjangoImageField=AirplaneImageFormField,
        help_text="Image content is validated; maximum file size is 5 MiB.",
    )

    class Meta:
        model = Airplane
        fields = ["id", "image"]
        extra_kwargs = {"image": {"required": True, "allow_empty_file": False}}

    def update(self, instance, validated_data):
        return update_airplane(instance=instance, data=validated_data)


class FlightSerializer(serializers.ModelSerializer):
    class Meta:
        model = Flight
        fields = [
            "id", "route", "airplane", "crew", "departure_time",
            "arrival_time",
        ]

    def create(self, validated_data):
        return save_flight(data=validated_data)

    def update(self, instance, validated_data):
        return save_flight(instance=instance, data=validated_data)


class FlightSummarySerializer(serializers.ModelSerializer):
    route = RouteReadSerializer(read_only=True)
    airplane = serializers.CharField(source="airplane.name", read_only=True)

    class Meta:
        model = Flight
        fields = [
            "id", "route", "airplane", "departure_time", "arrival_time",
        ]


class FlightListSerializer(FlightSummarySerializer):
    capacity = serializers.IntegerField(
        source="airplane.capacity", read_only=True
    )
    tickets_available = serializers.IntegerField(read_only=True)

    class Meta(FlightSummarySerializer.Meta):
        fields = FlightSummarySerializer.Meta.fields + [
            "capacity", "tickets_available",
        ]


class SeatSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ["row", "seat"]


class FlightDetailSerializer(FlightListSerializer):
    airplane = AirplaneSerializer(read_only=True)
    crew = CrewSerializer(many=True, read_only=True)
    taken_places = SeatSerializer(source="tickets", many=True, read_only=True)

    class Meta(FlightListSerializer.Meta):
        fields = FlightListSerializer.Meta.fields + ["crew", "taken_places"]


class TicketRequestSerializer(serializers.Serializer):
    flight = serializers.PrimaryKeyRelatedField(
        queryset=Flight.objects.select_related("airplane")
    )
    row = serializers.IntegerField(min_value=1)
    seat = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        flight = attrs["flight"]
        errors = {}
        if flight.departure_time <= timezone.now():
            errors["flight"] = "Cannot book a departed flight."
        for field, maximum in (
            ("row", flight.airplane.rows),
            ("seat", flight.airplane.seats_in_row),
        ):
            if attrs[field] > maximum:
                errors[field] = f"Must be between 1 and {maximum}."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class TicketReadSerializer(serializers.ModelSerializer):
    flight = FlightSummarySerializer(read_only=True)

    class Meta:
        model = Ticket
        fields = ["id", "row", "seat", "flight"]


class OrderReadSerializer(serializers.ModelSerializer):
    tickets = TicketReadSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ["id", "created_at", "tickets"]


class OrderCreateSerializer(serializers.ModelSerializer):
    tickets = TicketRequestSerializer(
        many=True, allow_empty=False
    )

    def get_fields(self):
        fields = super().get_fields()
        limit = settings.MAX_TICKETS_PER_ORDER
        fields["tickets"].max_length = limit
        fields["tickets"].validators.extend([
            MinLengthValidator(1), MaxLengthValidator(limit),
        ])
        fields["tickets"].help_text = (
            f"Between 1 and {limit} tickets per order, including staff orders."
        )
        return fields

    class Meta:
        model = Order
        fields = ["id", "created_at", "tickets"]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data):
        return reserve_order(
            user=self.context["request"].user,
            tickets=validated_data["tickets"],
        )

    def to_representation(self, instance):
        return OrderReadSerializer(instance, context=self.context).data
