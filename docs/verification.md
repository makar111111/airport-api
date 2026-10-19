# Verification record

Verified locally on 2026-10-19 after addressing the mentor review. See the
GitHub pull request for hosted CI status on the published commit.

| Check | Result |
| --- | --- |
| Python / Django | Local Python 3.10.20; Docker Python 3.10.22; Django 5.2.18 |
| Complete Docker/PostgreSQL suite | 180 tests passed, no skips, from the built image without a source bind mount |
| Local SQLite suite | 180 discovered, 170 passed, 10 PostgreSQL-only checks skipped |
| PostgreSQL concurrency | One winner per seat; conflicting airplane or crew schedules rejected, including different routes/airplanes for shared crew |
| Database constraints | Unique airports/routes/seats; nonblank names; direct ORM airplane schedule overlap rejected; adjacent flights accepted |
| Reservation integrity | Multiple flights and different seats on one flight accepted; duplicate seats rejected before locking; unrelated database errors preserved |
| Existing database upgrade | Migrations 0002 and 0003 applied; all existing catalogue counts and ticket/order references preserved |
| Flake8, local and Docker | Passed |
| Migration consistency | No changes detected |
| OpenAPI validation | Passed with warnings treated as failures |
| Real HTTP checks | 45 passed, including JWT, ownership, rollback, catalogue validation, filters, protected aircraft changes and image serving |
| Live OpenAPI | Order ticket list has minItems=1 and maxItems=100 |
| Docker startup | Application and PostgreSQL healthy; app on 127.0.0.1:8001 |
| Container settings | Both services use restart=unless-stopped, 1 CPU and 512 MiB; app runs as UID 10001 |
| Image contents | No .env, .git, .venv, SQLite DB or private artifacts |
| Image upload | Real PNG supplied with an .exe filename stored as .png and served successfully |
| Browsable API | Real authenticated flight/order pages captured in docs/screenshots |

Tests run against a disposable test database created and removed by Django.
The running development database contains generated sample flights and test
reservations. Local generated credentials and HTTP-check details are stored in
the ignored `artifacts/` directory. They are excluded from Git and Docker builds.

The source Cinema repository was inspected and tested without modifying it.
The implementation uses `develop`, with a pull request targeting `main` in the
project's own repository. Publication was explicitly approved by the user.
The pull request records the current GitHub Actions and review status.

The migration preflight reports pre-existing duplicate or malformed catalogue
records instead of deleting or relinking them. PostgreSQL also rejects existing
overlapping airplane schedules when the exclusion constraint is installed.
The successful local upgrade preserved five airports, six routes, six flights
and the original order/ticket. Additional HTTP checks then created a separate
test reservation.

## Reproduce

```sh
docker compose up --build -d --wait
docker compose run --rm app python manage.py test --settings=config.test_settings --noinput
docker compose run --rm app flake8
docker compose exec app python manage.py makemigrations --check --dry-run
docker compose exec app python manage.py spectacular --validate --fail-on-warn --file /tmp/openapi.yaml
```
