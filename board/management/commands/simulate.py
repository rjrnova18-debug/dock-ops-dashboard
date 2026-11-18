"""
python manage.py simulate [--steps N] [--seed S]

Advances the demo operation at the current time. One step moves each ready transport
by at most one stage; several steps at once move the board further.
"""
import random

from django.core.management.base import BaseCommand

from board import simulator
from board.models import local_now


class Command(BaseCommand):
    help = "Advance the demo operation by one or more steps at the current time."

    def add_arguments(self, parser):
        parser.add_argument("--steps", type=int, default=1, help="how many steps to run (default 1)")
        parser.add_argument("--seed", type=int, default=None, help="random seed, to repeat a run")

    def handle(self, *args, steps: int, seed: int | None, **options):
        rng = random.Random(seed)
        changes = sum(simulator.run_step(local_now(), rng) for _ in range(steps))
        self.stdout.write(self.style.SUCCESS(f"{changes} transport changes in {steps} step(s)."))
