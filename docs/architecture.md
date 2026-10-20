# Architecture

Airport API is a Django REST Framework application with email-based accounts,
a flight catalogue and seat reservations. PostgreSQL is the default database.
See the [README](../README.md) for setup, endpoints and request examples.

## Application boundaries

| Package | Responsibility |
| --- | --- |
| `config` | Environment configuration, database connection and URL routing |
| `user` | Email accounts, password handling, JWT and profile endpoints |
| `airport` | Catalogue, flight schedules, orders, tickets and admin |

Serializers validate API input and shape responses. Transactional operations
live in [airport/services.py](../airport/services.py), shared by API write
paths. The admin uses the same schedule validator and resource locking rules.
Models define relationships and database constraints. Shared image validation
in [airport/validators.py](../airport/validators.py) is used across API, admin
and model/file writes.

## Reservation flow

1. Validate the requested flights, seat coordinates and the 1–100 ticket limit.
2. Reject repeated `(flight, row, seat)` values before reservation queries.
3. Within a transaction, lock routes, airplanes and flights in primary-key order.
4. Check the current departure time, seat bounds and occupied places again.
5. Create the order and every ticket together; a failure rolls back the write.

An order may contain different seats on one flight or tickets for several
flights. Orders are visible only to their owner. Account deletion is protected
when orders reference the account; deactivation preserves booking history.

## Database and schedule protection

- Airport names, directed route pairs and `(flight, row, seat)` are unique.
- Constraints reject blank airport/crew names, nonpositive dimensions and
  arrival times that do not follow departure times.
- A PostgreSQL GiST exclusion constraint prevents overlapping flight intervals
  for one airplane, including direct ORM writes. Intervals are half-open:
  one flight may start exactly when the preceding flight arrives.
- Crew scheduling is protected by resource locks and schedule validation in
  the API/admin write paths. It has no equivalent database exclusion constraint.
- Resource locks follow route → airplane → crew, where applicable → flight,
  with primary-key ordering inside each group.
- Booked itineraries and airplane types/seating layouts are protected through
  the API and admin. Only recognized database conflicts become validation errors;
  unrelated integrity failures retain their original cause.

Migrations preflight duplicate or malformed catalogue records and stop with
diagnostics rather than deleting or relinking bookings. PostgreSQL requires
`btree_gist` for the airplane schedule constraint. See
[Updating an existing installation](../README.md#updating-an-existing-installation).

## Runtime

Docker Compose runs the application and PostgreSQL with health checks,
restart policies, resource limits and persistent database/media/static volumes.
SQLite is available only through an explicit debug configuration; it does not
provide the row-locking and exclusion guarantees required for concurrent use.
The Docker application uses Django's development server for local demonstrations.

See the [database diagram](database-diagram.svg), its
[editable draw.io source](database-diagram.drawio), the
[OpenAPI schema](schema.yaml) and the [testing guide](testing.md).
