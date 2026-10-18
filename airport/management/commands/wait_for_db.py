import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, OperationalError


class Command(BaseCommand):
    help = "Wait for the database, failing after a bounded number of retries."

    def add_arguments(self, parser):
        parser.add_argument("--max-retries", type=int, default=30)
        parser.add_argument("--interval", type=float, default=1)

    def handle(self, *args, **options):
        retries = options["max_retries"]
        interval = options["interval"]
        if retries < 1 or interval < 0:
            raise CommandError("Retries must be positive and interval >= 0.")

        for attempt in range(1, retries + 1):
            try:
                connection.ensure_connection()
            except OperationalError:
                connection.close()
                if attempt == retries:
                    raise CommandError("Database is unavailable.") from None
                self.stdout.write(
                    f"Waiting for database ({attempt}/{retries})"
                )
                time.sleep(interval)
            else:
                self.stdout.write(self.style.SUCCESS("Database is available."))
                return
