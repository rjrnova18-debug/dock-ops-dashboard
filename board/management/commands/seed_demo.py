"""
python manage.py seed_demo [--seed N]

Replaces every transport with invented demo data around the current time.
"""
import random

from django.core.management.base import BaseCommand
from django.db import transaction

from board import demo
from board.conf import get_ops_config
from board.models import Transport, local_now


class Command(BaseCommand):
    help = "Replace all transports with invented demo data around the current time."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=None,
                            help="random seed: the same seed at the same moment gives the same data")

    def handle(self, *args, seed: int | None, **options):
        transports = demo.seed_transports(local_now(), random.Random(seed), get_ops_config())
        with transaction.atomic():           # all or nothing: never a half-empty board
            Transport.objects.all().delete()
            Transport.objects.bulk_create(Transport.from_domain(t) for t in transports)
        self.stdout.write(self.style.SUCCESS(f"Created {len(transports)} demo transports."))
