# Testing

The API has automated checks for authentication, permissions, catalogue
validation, reservations, scheduling, images, filters and migrations.
Use PostgreSQL for the complete suite, including database constraints and
concurrent writes. See the [Quick start](../README.md#quick-start) to prepare
the environment and start the services.

## Full PostgreSQL suite

```sh
docker compose run --rm app python manage.py test --settings=config.test_settings --noinput
```

Expected: the suite ends with `OK` and exit code 0. Django creates and removes
a separate test database. Test settings use a fast password hasher and disable
request throttling; application runtime settings retain normal password hashing
and rate limits.

Coverage includes:

- Email/JWT authentication, staff permissions and order ownership.
- Unique airports/routes, trimmed nonblank names and numeric/time constraints.
- Early duplicate-seat rejection, multi-flight orders and complete rollback.
- Concurrent requests for the same seat, airplane or crew member.
- Direct ORM airplane overlap rejection and adjacent schedule intervals.
- Protected changes to booked airplanes, itineraries and account deletion.
- Specific database error classification without masking unrelated failures.
- Invalid and combined filters, repeated parameters and stable ordering.
- Image content, the 5 MiB limit, detected extensions and file-stream handling.
- Migration preflight and preservation of existing booking references.

Tests live in [airport/tests](../airport/tests/) and [user/tests](../user/tests/).

## Migration, schema and style checks

```sh
docker compose run --rm app python manage.py makemigrations --check --dry-run
docker compose run --rm app python manage.py spectacular --validate --fail-on-warn
docker compose run --rm app flake8
```

| Check | Expected result |
| --- | --- |
| Migration consistency | `No changes detected`, exit code 0; this checks model state without applying migrations |
| OpenAPI | Valid schema, exit code 0, no warnings or validation errors |
| Flake8 | No diagnostic output, exit code 0 |

## Local SQLite checks

With the Python dependencies installed and `DB_ENGINE` unset or explicitly
set to `sqlite`, run:

```sh
python manage.py test --settings=config.test_settings --noinput
python -m flake8
```

PostgreSQL-specific tests are skipped on SQLite. A green SQLite run does not
verify row locking, concurrency or the airplane exclusion constraint. CI runs
the suite on PostgreSQL alongside migration, schema and style checks.

## Running-service checks

```sh
docker compose ps
```

Both services should report healthy. Open
[Swagger UI](http://127.0.0.1:8001/api/doc/swagger/) and follow the
[authentication and booking walkthrough](../README.md#authentication-and-booking-walkthrough)
to exercise the protected endpoints. A rejected multi-ticket reservation should
leave no partial order. Another user's order should return 404.
