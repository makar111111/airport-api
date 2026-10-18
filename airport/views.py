from django.db import IntegrityError, transaction
from django.db.models import Count, F, Prefetch
from django.db.models.deletion import ProtectedError
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from airport.filters import (
    AirplaneFilterSerializer,
    AirportFilterSerializer,
    FlightFilterSerializer,
    RouteFilterSerializer,
)
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
from airport.permissions import IsStaffOrAuthenticatedReadOnly
from airport.serializers import (
    AirplaneImageSerializer,
    AirplaneSerializer,
    AirplaneTypeSerializer,
    AirportSerializer,
    CrewSerializer,
    FlightDetailSerializer,
    FlightListSerializer,
    FlightSerializer,
    OrderCreateSerializer,
    OrderReadSerializer,
    RouteReadSerializer,
    RouteSerializer,
)


class CatalogueViewSet(viewsets.ModelViewSet):
    permission_classes = [IsStaffOrAuthenticatedReadOnly]

    def perform_destroy(self, instance):
        try:
            with transaction.atomic():
                locked = get_object_or_404(
                    type(instance).objects.select_for_update(), pk=instance.pk
                )
                locked.delete()
        except (ProtectedError, IntegrityError) as error:
            raise ValidationError({
                "detail": "This object is referenced and cannot be deleted."
            }) from error

    def validated_filters(self, serializer_class):
        # A plain dict preserves an omitted boolean. DRF treats QueryDict as
        # HTML form data and otherwise turns an omitted checkbox into False.
        serializer = serializer_class(
            data=dict(self.request.query_params.items())
        )
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


@extend_schema_view(list=extend_schema(parameters=[AirportFilterSerializer]))
class AirportViewSet(CatalogueViewSet):
    queryset = Airport.objects.all()
    serializer_class = AirportSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "list":
            filters = self.validated_filters(AirportFilterSerializer)
            if "name" in filters:
                queryset = queryset.filter(name__icontains=filters["name"])
            if "city" in filters:
                queryset = queryset.filter(
                    closest_big_city__icontains=filters["city"]
                )
        return queryset


@extend_schema_view(list=extend_schema(parameters=[RouteFilterSerializer]))
class RouteViewSet(CatalogueViewSet):
    queryset = Route.objects.select_related("source", "destination")
    serializer_class = RouteSerializer

    def get_serializer_class(self):
        if self.action in ("list", "retrieve"):
            return RouteReadSerializer
        return self.serializer_class

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "list":
            filters = self.validated_filters(RouteFilterSerializer)
            for field in ("source", "destination"):
                if field in filters:
                    queryset = queryset.filter(**{
                        f"{field}_id": filters[field]
                    })
        return queryset


class CrewViewSet(CatalogueViewSet):
    queryset = Crew.objects.all()
    serializer_class = CrewSerializer


class AirplaneTypeViewSet(CatalogueViewSet):
    queryset = AirplaneType.objects.all()
    serializer_class = AirplaneTypeSerializer


@extend_schema_view(list=extend_schema(parameters=[AirplaneFilterSerializer]))
class AirplaneViewSet(CatalogueViewSet):
    queryset = Airplane.objects.select_related("airplane_type")
    serializer_class = AirplaneSerializer

    def get_serializer_class(self):
        if self.action == "upload_image":
            return AirplaneImageSerializer
        return self.serializer_class

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "list":
            filters = self.validated_filters(AirplaneFilterSerializer)
            if "airplane_type" in filters:
                queryset = queryset.filter(
                    airplane_type_id=filters["airplane_type"]
                )
        return queryset

    @extend_schema(
        request=AirplaneImageSerializer, responses=AirplaneSerializer
    )
    @action(
        detail=True, methods=["post"], url_path="upload-image",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_image(self, request, pk=None):
        airplane = self.get_object()
        serializer = self.get_serializer(airplane, data=request.data)
        serializer.is_valid(raise_exception=True)
        airplane = serializer.save()
        return Response(
            AirplaneSerializer(
                airplane, context=self.get_serializer_context()
            ).data,
            status=status.HTTP_200_OK,
        )


@extend_schema_view(list=extend_schema(parameters=[FlightFilterSerializer]))
class FlightViewSet(CatalogueViewSet):
    queryset = Flight.objects.all()
    serializer_class = FlightSerializer

    def get_serializer_class(self):
        if self.action == "list":
            return FlightListSerializer
        if self.action == "retrieve":
            return FlightDetailSerializer
        return self.serializer_class

    def get_queryset(self):
        queryset = super().get_queryset().select_related(
            "route__source", "route__destination", "airplane__airplane_type",
        ).annotate(
            tickets_available=(
                F("airplane__rows") * F("airplane__seats_in_row")
                - Count("tickets")
            ),
        )
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("crew", "tickets")
        if self.action == "list":
            filters = self.validated_filters(FlightFilterSerializer)
            for field in ("source", "destination"):
                if field in filters:
                    queryset = queryset.filter(**{
                        f"route__{field}_id": filters[field]
                    })
            if "date" in filters:
                queryset = queryset.filter(
                    departure_time__date=filters["date"]
                )
            if "available" in filters:
                if filters["available"]:
                    queryset = queryset.filter(tickets_available__gt=0)
                else:
                    queryset = queryset.filter(tickets_available=0)
            queryset = queryset.order_by(filters["ordering"], "id")
        return queryset


@extend_schema_view(
    create=extend_schema(
        request=OrderCreateSerializer, responses={201: OrderReadSerializer}
    ),
)
class OrderViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Order.objects.all()
    serializer_class = OrderReadSerializer

    def get_serializer_class(self):
        if self.action == "create":
            return OrderCreateSerializer
        return self.serializer_class

    def get_queryset(self):
        queryset = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):
            return queryset.none()
        tickets = Ticket.objects.select_related(
            "flight__route__source", "flight__route__destination",
            "flight__airplane",
        )
        return queryset.filter(user=self.request.user).prefetch_related(
            Prefetch("tickets", queryset=tickets)
        )
