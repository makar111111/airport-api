# Airport API portfolio project

Implement the airport domain from the portfolio assignment as a standalone
Django REST Framework API. Authenticated passengers can find flights and reserve
seats; staff manage airports, routes, aircraft, crews and schedules.

Additional booking rules reject departed flights, invalid or duplicate seats,
conflicting airplane/crew schedules and changes to booked itineraries, airplane
types or seat layouts. Reservations are atomic, use PostgreSQL row locks and
enforce seat uniqueness in the database. Orders are visible only to their owner,
and account deletion cannot erase bookings.

Airport names and directed routes are unique. PostgreSQL excludes overlapping
airplane schedules even for direct ORM writes; crew scheduling is serialized
with resource locks. Image content and the 5 MiB size limit are validated across
API/admin/model writes, with extensions derived from detected image content.
The API documents its 1–100 ticket limit and single-value filter contract.

Includes email/JWT authentication, staff image uploads, browsable API, admin,
Swagger/ReDoc, PostgreSQL Docker Compose, demo data and GitHub Actions.
See the README for setup, permissions, authentication and booking examples.

## Validation

- All 180 tests passed in Docker/PostgreSQL, with no skipped tests, covering
  concurrent reservations, airplane and crew
  scheduling, booking/deletion, migration safety and precise error handling.
- All 45 real HTTP checks passed, covering authentication, booking rollback,
  filters, catalogue validation, protected aircraft changes and images.
- Flake8, migration consistency and OpenAPI validation passed.
- Docker application and database health checks passed.
- Upgrading the existing database preserved its catalogue, original order
  and ticket references.

The [mentor remediation record](mentor-fixes.md) maps all 17 comments to changes
and regression tests. README includes setup and expected verification results.

## Database diagram

![Airport database structure](database-diagram.svg)

Editable source: `docs/database-diagram.drawio`.

## API screenshots

![Swagger](screenshots/swagger.png)
![Flights](screenshots/flights.png)
![Orders](screenshots/orders.png)
