# Airport API portfolio project

Implement the airport domain from the portfolio assignment as a standalone
Django REST Framework API. Authenticated passengers can find flights and reserve
seats; staff manage airports, routes, aircraft, crews and schedules.

Additional booking rules reject departed flights, invalid or duplicate seats,
conflicting airplane/crew schedules and changes to booked itineraries or seat
layouts. Reservations are atomic, use PostgreSQL row locks and enforce seat
uniqueness in the database. Orders are visible only to their owner.

Includes email/JWT authentication, staff image uploads, browsable API, admin,
Swagger/ReDoc, PostgreSQL Docker Compose, demo data and GitHub Actions.
See the README for setup, permissions, authentication and booking examples.

## Validation

- 107 tests passed against PostgreSQL, including concurrent reservation,
  scheduling and booking/deletion tests.
- 36 real HTTP checks passed, including full booking rollback and image serving.
- Flake8, migration consistency and OpenAPI validation passed.
- Docker application and database health checks passed.

## Database diagram

![Airport database structure](database-diagram.svg)

Editable source: `docs/database-diagram.drawio`.

## API screenshots

![Swagger](screenshots/swagger.png)
![Flights](screenshots/flights.png)
![Orders](screenshots/orders.png)
