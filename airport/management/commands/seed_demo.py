from datetime import datetime, time, timedelta, timezone as datetime_timezone

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from airport.models import (
    Airplane, AirplaneType, Airport, Crew, Flight, Route,
)


class Command(BaseCommand):
    help = "Add sample European flights without changing existing data."

    @transaction.atomic
    def handle(self, *args, **options):
        airports = []
        for name, city in (
            ("London Heathrow", "London"),
            ("Paris Charles de Gaulle", "Paris"),
            ("Amsterdam Schiphol", "Amsterdam"),
            ("Berlin Brandenburg", "Berlin"),
        ):
            airport, _ = Airport.objects.get_or_create(
                name=f"Demo: {name}", defaults={"closest_big_city": city}
            )
            airports.append(airport)

        routes = []
        for source, destination, distance in (
            (0, 1, 350), (1, 2, 430), (2, 3, 580),
            (3, 2, 580), (2, 1, 430), (1, 0, 350),
        ):
            route, _ = Route.objects.get_or_create(
                source=airports[source], destination=airports[destination],
                defaults={"distance": distance},
            )
            routes.append(route)

        airplanes = []
        for name, model, rows, seats in (
            ("DEMO-A320", "Airbus A320", 30, 6),
            ("DEMO-B738", "Boeing 737-800", 31, 6),
            ("DEMO-E190", "Embraer 190", 25, 4),
        ):
            airplane_type, _ = AirplaneType.objects.get_or_create(name=model)
            airplane, _ = Airplane.objects.get_or_create(
                name=name,
                defaults={
                    "airplane_type": airplane_type,
                    "rows": rows, "seats_in_row": seats,
                },
            )
            airplanes.append(airplane)

        crew = []
        for first_name, last_name in (
            ("Alex", "Demo Morgan"), ("Marta", "Demo Kowalska"),
            ("Oliver", "Demo Schmidt"), ("Sofia", "Demo Rossi"),
        ):
            member, _ = Crew.objects.get_or_create(
                first_name=first_name, last_name=last_name
            )
            crew.append(member)

        tomorrow = (
            timezone.now().astimezone(datetime_timezone.utc).date()
            + timedelta(days=1)
        )
        created_count = existing_count = conflict_count = 0
        for index, route in enumerate(routes):
            departure = datetime.combine(
                tomorrow + timedelta(days=index // 3),
                time(8 + 4 * (index % 3), tzinfo=datetime_timezone.utc),
            )
            arrival = departure + timedelta(hours=2)
            airplane = airplanes[index % len(airplanes)]
            members = crew[:2] if index % 2 == 0 else crew[2:]
            if Flight.objects.filter(
                route=route, airplane=airplane, departure_time=departure
            ).exists():
                existing_count += 1
                continue
            overlaps = Flight.objects.filter(
                departure_time__lt=arrival, arrival_time__gt=departure
            ).filter(Q(airplane=airplane) | Q(crew__in=members))
            if overlaps.exists():
                conflict_count += 1
                continue
            flight = Flight(
                route=route, airplane=airplane,
                departure_time=departure, arrival_time=arrival,
            )
            flight.full_clean()
            flight.save()
            flight.crew.set(members)
            created_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Demo flights: {created_count} created, "
            f"{existing_count} already present, "
            f"{conflict_count} skipped due to schedule conflicts."
        ))
