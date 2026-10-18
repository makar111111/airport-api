# Verification record

Verified locally on 2026-10-18. See the GitHub pull request for hosted CI status.

| Check | Result |
| --- | --- |
| Python / Django | Local Python 3.10.20; Docker Python 3.10.22; Django 5.2.18 |
| Complete Docker/PostgreSQL suite | 107 tests passed, no skips |
| Local SQLite suite | 107 discovered, 104 passed, 3 PostgreSQL-only checks skipped |
| PostgreSQL concurrency | One winner per seat; no overlapping aircraft schedules; booking vs deletion returns 400 |
| Flake8, local and Docker | Passed |
| Migration consistency | No changes detected |
| OpenAPI validation | Passed with warnings treated as failures |
| Real HTTP checks | 36 passed, including JWT, ownership, rollback and image serving |
| Docker startup | Application and PostgreSQL healthy; app on 127.0.0.1:8001 |
| Demo command repeated | 0 created, 6 already present; existing booking preserved |
| Image contents | Non-root UID 10001; no .env, .git, .venv, SQLite DB or private artifacts |
| Browsable API | Real authenticated flight/order pages captured in docs/screenshots |

Tests run against a disposable test database created and removed by Django.
The running development database contains generated sample flights and a test
reservation. Local generated credentials and HTTP-check details are stored in
the ignored `artifacts/` directory. They are excluded from Git and Docker builds.

The source Cinema repository was inspected and tested without modifying it.
The implementation uses `develop`, with a pull request targeting `main` in the
project's own repository. Publication was explicitly approved by the user.
The pull request records the current GitHub Actions and review status.

## Reproduce

```sh
docker compose up --build -d --wait
docker compose run --rm app python manage.py test --settings=config.test_settings --noinput
docker compose run --rm app flake8
docker compose exec app python manage.py makemigrations --check --dry-run
docker compose exec app python manage.py spectacular --validate --fail-on-warn --file /tmp/openapi.yaml
```
