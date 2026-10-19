"""Transactional writes shared by the API and booking workflow."""

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from airport.db_errors import is_airplane_overlap, is_seat_conflict
from airport.models import Airplane, Crew, Flight, Order, Route, Ticket


class _FlightChanged(Exception):
    """Retry after a flight was assigned to another airplane while waiting."""


def _lock_airplanes(airplane_ids):
    return {
        airplane.pk: airplane
        for airplane in Airplane.objects.select_for_update().filter(
            pk__in=airplane_ids
        ).order_by("pk")
    }


def _flight_snapshot(flight_ids):
    return {
        pk: (route_id, airplane_id)
        for pk, route_id, airplane_id in Flight.objects.filter(
            pk__in=flight_ids
        ).values_list("pk", "route_id", "airplane_id")
    }


def _lock_routes(route_ids):
    return list(
        Route.objects.select_for_update().filter(
            pk__in=route_ids
        ).order_by("pk")
    )


def reserve_order(*, user, tickets):
    """Reserve the complete request, or persist nothing.

    All writers take route, airplane, then flight locks in primary-key order.
    This also serializes seat checks with airplane capacity changes. PostgreSQL
    enforces row locking; SQLite is suitable only for local single-user demos.
    """
    requested = set()
    for ticket in tickets:
        place = (ticket["flight"].pk, ticket["row"], ticket["seat"])
        if place in requested:
            raise ValidationError({
                "tickets": "The same seat was requested more than once."
            })
        requested.add(place)
    flight_ids = sorted({place[0] for place in requested})
    for _ in range(3):
        snapshot = _flight_snapshot(flight_ids)
        try:
            with transaction.atomic():
                _lock_routes({value[0] for value in snapshot.values()})
                airplanes = _lock_airplanes({
                    value[1] for value in snapshot.values()
                })
                flights = {
                    flight.pk: flight
                    for flight in Flight.objects.select_for_update().filter(
                        pk__in=flight_ids
                    ).order_by("pk")
                }
                if set(flights) != set(flight_ids):
                    raise ValidationError({
                        "tickets": "A flight no longer exists."
                    })
                if any(
                    (flight.route_id, flight.airplane_id)
                    != snapshot.get(flight.pk)
                    for flight in flights.values()
                ):
                    raise _FlightChanged
                taken = set(
                    Ticket.objects.filter(
                        flight_id__in=flight_ids
                    ).values_list("flight_id", "row", "seat")
                )
                now = timezone.now()
                for ticket in tickets:
                    flight = flights[ticket["flight"].pk]
                    airplane = airplanes[flight.airplane_id]
                    if flight.departure_time <= now:
                        raise ValidationError({
                            "tickets": "Cannot book a departed flight."
                        })
                    if not (
                        1 <= ticket["row"] <= airplane.rows
                        and 1 <= ticket["seat"] <= airplane.seats_in_row
                    ):
                        raise ValidationError({
                            "tickets": "Seat is outside the seating plan."
                        })
                    place = (flight.pk, ticket["row"], ticket["seat"])
                    if place in taken:
                        raise ValidationError({
                            "tickets": "A requested seat is already reserved."
                        })
                order = Order.objects.create(user=user)
                Ticket.objects.bulk_create([
                    Ticket(
                        order=order, flight_id=flight_id, row=row, seat=seat
                    )
                    for flight_id, row, seat in sorted(requested)
                ])
                return order
        except _FlightChanged:
            continue
        except IntegrityError as error:
            # Catch outside atomic after the failed transaction rolls back.
            if not is_seat_conflict(error):
                raise
            raise ValidationError({
                "tickets": "A requested seat is no longer available."
            }) from error
    raise ValidationError({
        "tickets": "Flight changed; retry your reservation."
    })


def save_flight(*, instance=None, data):
    for _ in range(3):
        if instance is None:
            old_airplane_id = None
            old_route_id = None
            current_crew_ids = []
        else:
            snapshot = _flight_snapshot([instance.pk])
            if instance.pk not in snapshot:
                raise NotFound("Flight no longer exists.")
            old_route_id, old_airplane_id = snapshot[instance.pk]
            current_crew_ids = list(
                Flight.objects.get(pk=instance.pk).crew.values_list(
                    "pk", flat=True
                )
            )
        airplane_id = (
            data["airplane"].pk if "airplane" in data else old_airplane_id
        )
        route_id = data["route"].pk if "route" in data else old_route_id
        crew_ids = sorted({
            member.pk for member in data["crew"]
        }) if "crew" in data else sorted(current_crew_ids)
        try:
            with transaction.atomic():
                routes = _lock_routes({
                    pk for pk in (old_route_id, route_id) if pk is not None
                })
                if route_id not in {route.pk for route in routes}:
                    raise ValidationError({"route": "Route no longer exists."})
                airplanes = _lock_airplanes({
                    pk for pk in (old_airplane_id, airplane_id)
                    if pk is not None
                })
                if airplane_id not in airplanes:
                    raise ValidationError({
                        "airplane": "Airplane no longer exists."
                    })
                locked_crew = list(
                    Crew.objects.select_for_update().filter(
                        pk__in=crew_ids
                    ).order_by("pk")
                )
                if len(locked_crew) != len(crew_ids):
                    raise ValidationError({
                        "crew": "A crew member no longer exists."
                    })
                if instance is None:
                    flight = Flight()
                else:
                    try:
                        flight = Flight.objects.select_for_update().get(
                            pk=instance.pk
                        )
                    except Flight.DoesNotExist as error:
                        raise NotFound("Flight no longer exists.") from error
                    if (flight.route_id, flight.airplane_id) != (
                        old_route_id, old_airplane_id
                    ):
                        raise _FlightChanged
                    if "crew" not in data and sorted(
                        flight.crew.values_list("pk", flat=True)
                    ) != crew_ids:
                        raise _FlightChanged
                _validate_flight(flight, data, airplane_id, crew_ids)
                for field, value in data.items():
                    if field != "crew":
                        setattr(flight, field, value)
                flight.save()
                flight.crew.set(locked_crew)
                return flight
        except _FlightChanged:
            continue
        except IntegrityError as error:
            if not is_airplane_overlap(error):
                raise
            raise ValidationError({
                "airplane": "Airplane is already assigned during this time."
            }) from error
    raise ValidationError({"detail": "Flight changed; retry your update."})


def _validate_flight(flight, data, airplane_id, crew_ids):
    departure = data.get("departure_time", flight.departure_time)
    arrival = data.get("arrival_time", flight.arrival_time)
    if flight.pk and flight.tickets.exists():
        protected = ("route", "airplane", "departure_time", "arrival_time")
        if any(
            field in data and data[field] != getattr(flight, field)
            for field in protected
        ):
            raise ValidationError({
                "detail": (
                    "A booked flight's route, airplane and times are fixed."
                )
            })
    validate_flight_schedule(
        airplane=airplane_id, crew=crew_ids,
        departure_time=departure, arrival_time=arrival,
        exclude_flight_id=flight.pk,
    )


def validate_flight_schedule(
    *, airplane, crew, departure_time, arrival_time, exclude_flight_id=None
):
    """Validate a schedule; callers acquire resource locks before saving it."""
    if arrival_time <= departure_time:
        raise ValidationError({
            "arrival_time": "Arrival must be after departure."
        })
    overlapping = Flight.objects.filter(
        departure_time__lt=arrival_time, arrival_time__gt=departure_time,
    ).exclude(pk=exclude_flight_id)
    if overlapping.filter(airplane=airplane).exists():
        raise ValidationError({
            "airplane": "Airplane is already assigned during this time."
        })
    if crew and overlapping.filter(crew__in=crew).exists():
        raise ValidationError({
            "crew": "A crew member is already assigned during this time."
        })


def update_airplane(*, instance, data):
    with transaction.atomic():
        airplane = Airplane.objects.select_for_update().get(pk=instance.pk)
        changed_seating_plan = any(
            field in data and data[field] != getattr(airplane, field)
            for field in ("rows", "seats_in_row", "airplane_type")
        )
        if changed_seating_plan and Ticket.objects.filter(
            flight__airplane=airplane
        ).exists():
            raise ValidationError({
                "detail": (
                    "Cannot change a booked airplane's type or seating plan."
                )
            })
        for field, value in data.items():
            setattr(airplane, field, value)
        airplane.save()
        return airplane


def update_route(*, instance, data):
    with transaction.atomic():
        route = Route.objects.select_for_update().get(pk=instance.pk)
        source_id = (
            data["source"].pk if "source" in data else route.source_id
        )
        destination_id = (
            data["destination"].pk
            if "destination" in data else route.destination_id
        )
        if source_id == destination_id:
            raise ValidationError({
                "destination": "Source and destination must be different."
            })
        changed_airports = any(
            field in data and data[field] != getattr(route, field)
            for field in ("source", "destination")
        )
        if changed_airports and Ticket.objects.filter(
            flight__route=route
        ).exists():
            raise ValidationError({
                "detail": "Cannot change the airports of a booked route."
            })
        for field, value in data.items():
            setattr(route, field, value)
        route.save()
        return route
