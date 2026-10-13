import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.services.scheduled_audit import run_due_schedules


class Command(BaseCommand):
    help = "Run every enabled audit schedule that is due."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true",
                            help="Keep running and check again every --every seconds (development).")
        parser.add_argument("--every", type=int, default=20)

    def handle(self, *args, **opts):
        try:
            while True:
                audited = run_due_schedules()
                if audited:
                    self.stdout.write(f"{timezone.now():%H:%M:%S} audited {audited} device(s)")
                if not opts["loop"]:
                    break
                time.sleep(opts["every"])
        except KeyboardInterrupt:
            self.stdout.write("Stopped.")