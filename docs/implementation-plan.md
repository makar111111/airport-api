# Airport API implementation plan

Goal: deliver a standalone DRF portfolio project based on the completed Cinema
API, covering the airport diagram and a small set of useful booking rules.

Architecture: `config` owns configuration, `user` owns email accounts and JWT,
`airport` owns catalogue, scheduling, orders and tickets. PostgreSQL is used in
Docker and CI; SQLite is an optional quick local development database.

## Delivery checklist

- [x] Verify the Cinema API baseline before using its patterns.
- [x] Add email-only accounts, safe password handling, JWT and account tests.
- [x] Add Airport, Route, Crew, AirplaneType, Airplane, Flight, Order and Ticket;
      generate migrations and register admin pages.
- [x] Test positive dimensions, different route endpoints, arrival after
      departure, seat bounds and database-level unique seat constraints.
- [x] Implement staff-only catalogue management, authenticated reads,
      documented flight filters and image uploads.
- [x] Implement personal orders with atomic multi-ticket booking, locked
      flights, no departed-flight bookings and duplicate-seat protection.
- [x] Validate conflicting airplane/crew schedules through the API; prevent
      unsafe edits to flights and seat layouts that already have bookings.
- [x] Add Docker/PostgreSQL, bounded database wait command and CI.
- [x] Add an idempotent demo-data command without embedded user passwords.
- [x] Write an English README with setup, authentication, features, filters,
      booking examples, verification and source attribution.
- [x] Add an editable draw.io database diagram and a rendered SVG.
- [x] Run tests on SQLite and PostgreSQL, style, migrations, OpenAPI validation,
      real HTTP booking/image checks and capture browsable API screenshots.
- [x] Review requirements and implementation independently; fix material gaps.
- [x] Request approval for creating the public GitHub repository, commits,
      push and a `develop` to `main` pull request with screenshots.

Publication is a separate final step; preserve the existing Cinema repository.
