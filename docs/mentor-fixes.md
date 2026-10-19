# Mentor review remediation

The following changes address the 17 comments supplied on 2026-10-19. Targeted
regressions reproduced the confirmed faults before their fixes; requested
cases that already worked now have explicit coverage and documentation.

| # | Review point | Change and evidence |
| --- | --- | --- |
| 1 | Airport names were not unique | `Airport.name` is unique in the database and API; catalogue regression tests reject duplicates. |
| 2 | Duplicate directed routes | `unique_route_airports` protects `(source, destination)`; the reverse direction remains a different route. |
| 3 | Reservation errors masked unrelated failures | Only the named seat-uniqueness violation is translated to an occupied-seat error. Other failures retain their original cause and reach Django's error logging. |
| 4 | Validate duplicates before locks | Repeated `(flight, row, seat)` requests fail before reservation queries or locks. Different seats on one flight and tickets for multiple flights remain supported and tested. |
| 5 | Changing the type of a booked airplane | Service, API and admin protect `airplane_type` along with seating dimensions after booking. |
| 6 | Concurrent schedule conflicts | PostgreSQL `flight_airplane_no_overlap` excludes overlapping intervals, including direct ORM writes. Deterministic concurrent tests cover shared airplanes and shared crew on different airplanes/routes; crew assignments use resource locks because the relationship is many-to-many. |
| 7 | Delete handler masked every integrity error | Only driver-reported FK violations and Django `ProtectedError` produce the protected-object response. Unrelated integrity failures propagate. |
| 8 | Repeated query parameters silently lost | Supported filters explicitly accept one value; repeats receive a field-level error. Missing boolean filters remain absent. The contract is in OpenAPI and README. |
| 9 | Filtering and ordering coverage | Tests cover invalid/impossible dates, booleans, unsupported ordering, full flights, unknown airports, combined filters, UTC day boundaries and stable ties. |
| 10 | Ticket serializer accepted departed flights | Serializer validation checks departure and seat bounds early. Reservation checks still repeat under locks. |
| 11 | Ticket limit was undocumented | `MAX_TICKETS_PER_ORDER=100` configures serializer limits, OpenAPI and README; the same limit applies to staff. |
| 12 | Image size could bypass the API | A reusable 5 MiB/content validator is attached to the model field and used for API, admin, model and direct file saves. |
| 13 | Image extension trusted the supplied filename | Pillow detects the actual format; UUID filenames use a canonical detected extension. Tests cover PNG content disguised as `.jpg` or `.exe`, content validation and stream preservation. |
| 14 | Blank names could be stored | Airport and crew names are trimmed; model/API validation and database checks reject whitespace-only names. |
| 15 | SQLite was the default | PostgreSQL is the application/environment/Compose default. SQLite requires explicit selection and debug mode; deployment with debug disabled rejects it. |
| 16 | Docker reliability settings | Both services have `restart: unless-stopped`, a one-CPU/512-MiB limit and health checks. Named volumes preserve data. |
| 17 | Verification command results were unclear | README maps each test/style/migration/schema command to its expected output and exit status. |

The separate Codex review finding was also addressed: `Order.user` now uses
`PROTECT`. Deleting an account with orders is rejected without erasing tickets;
deactivating the account preserves the booking history.

## Data-preserving migration

Migration `0002_catalogue_validation` checks existing records before changing
the schema. Duplicates and whitespace names stop the migration with diagnostic
record information instead of deleting or relinking existing bookings. A test
using the historical initial schema and an existing ticket verifies this.

Migration `0003_airplane_schedule_exclusion` installs `btree_gist` and a
PostgreSQL exclusion constraint with the half-open interval `[departure,
arrival)`. A flight may start when the previous one arrives. SQLite explicitly
skips this PostgreSQL-only operation; concurrency and exclusion tests run on
PostgreSQL locally and in CI.

## Regression tests

- `test_catalogue_review.py`: uniqueness, names, ticket validation/limits,
  booked airplane admin fields, account deletion and migration preservation.
- `test_image_review.py`: consistent validation across write paths, canonical
  extensions, exact size boundary and stream position.
- `test_reservation_review.py`: early duplicates, multi-flight orders, complete
  rollback, precise exception classification and HTTP error logging.
- `test_schedule_review.py`: booked airplane type, direct database enforcement,
  adjacent flights and deterministic resource contention.
- `test_filter_review.py` and `test_delete_review.py`: filter behavior and
  narrow handling of protected deletes.
- `test_configuration_review.py`: PostgreSQL defaults and explicit SQLite guard.

See [the verification record](verification.md) for the completed test runs.
