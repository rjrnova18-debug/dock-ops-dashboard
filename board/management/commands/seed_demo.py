"""
python manage.py seed_demo [--seed N]

Replaces every transport with invented demo data around the current time. When
settings.DEMO_USER_PASSWORD is set, it also creates (or updates) the "demo" user, who can
see the history and nothing else, so visitors of a deployed demo can sign in.
"""
import random

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from board import demo
from board.conf import get_ops_config
from board.models import HISTORY_VIEWERS_GROUP, Transport, local_now

DEMO_USERNAME = "demo"


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

        if settings.DEMO_USER_PASSWORD:
            self.create_demo_user(settings.DEMO_USER_PASSWORD)
            self.stdout.write(self.style.SUCCESS(f'User "{DEMO_USERNAME}" can sign in to see the history.'))

    def create_demo_user(self, password: str) -> None:
        user, _ = get_user_model().objects.get_or_create(username=DEMO_USERNAME)
        try:
            validate_password(password, user)            # the same rules as any other account
        except ValidationError as error:
            raise CommandError(f"DEMO_USER_PASSWORD is not accepted: {' '.join(error.messages)}") from None
        user.set_password(password)                      # stored hashed, never as given
        user.is_staff = user.is_superuser = False
        user.save()
        user.groups.add(Group.objects.get(name=HISTORY_VIEWERS_GROUP))
