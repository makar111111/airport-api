"""Recognize specific database constraints without masking other failures."""

import sqlite3


AIRPLANE_OVERLAP_CONSTRAINT = "flight_airplane_no_overlap"
_SEAT_UNIQUE_SIGNATURE = (
    "UNIQUE constraint failed: airport_ticket.flight_id, "
    "airport_ticket.row, airport_ticket.seat"
)


def _database_cause(error):
    """Django wraps driver errors and preserves them as an explicit cause."""
    seen = set()
    while error.__cause__ is not None and id(error) not in seen:
        seen.add(id(error))
        error = error.__cause__
    return error


def _postgres_constraint(error, sqlstate, constraint_name=None):
    state = getattr(error, "sqlstate", None) or getattr(error, "pgcode", None)
    if state != sqlstate:
        return False
    return constraint_name is None or getattr(
        getattr(error, "diag", None), "constraint_name", None
    ) == constraint_name


def is_seat_conflict(error):
    """Only a violation of the unique (flight, row, seat) constraint."""
    cause = _database_cause(error)
    if _postgres_constraint(cause, "23505", "unique_flight_seat"):
        return True
    # Python 3.10 does not expose SQLite's extended error codes. The native
    # exception type plus the exact column signature identifies this one key.
    return (
        isinstance(cause, sqlite3.IntegrityError)
        and str(cause) == _SEAT_UNIQUE_SIGNATURE
    )


def is_reference_conflict(error):
    """A driver-reported foreign key violation, including a delete race."""
    cause = _database_cause(error)
    if _postgres_constraint(cause, "23503"):
        return True
    if not isinstance(cause, sqlite3.IntegrityError):
        return False
    code = getattr(cause, "sqlite_errorcode", None)
    if code is not None:
        return code == 787  # SQLITE_CONSTRAINT_FOREIGNKEY
    return str(cause) == "FOREIGN KEY constraint failed"


def is_airplane_overlap(error):
    """The PostgreSQL exclusion constraint for one airplane's time range."""
    return _postgres_constraint(
        _database_cause(error), "23P01", AIRPLANE_OVERLAP_CONSTRAINT,
    )
