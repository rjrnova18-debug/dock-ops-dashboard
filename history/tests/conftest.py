"""Users for the history tests: one in the "History viewers" group, one without access."""
from datetime import datetime
from random import Random

import pytest
from django.contrib.auth.models import Group

from board.demo import seed_transports
from board.models import HISTORY_VIEWERS_GROUP, Transport
from dockops.models import OpsConfig

PASSWORD = "a-long-demo-password"


@pytest.fixture
def viewer(django_user_model):
    """A user given access the way an administrator would: by joining the group."""
    user = django_user_model.objects.create_user("viewer", password=PASSWORD)
    user.groups.add(Group.objects.get(name=HISTORY_VIEWERS_GROUP))
    return user


@pytest.fixture
def outsider(django_user_model):
    return django_user_model.objects.create_user("outsider", password=PASSWORD)


@pytest.fixture
def seeded(db):
    """The demo operation around a fixed Thursday, saved in the database."""
    now = datetime(2026, 11, 12, 10, 42)
    Transport.objects.bulk_create(Transport.from_domain(t) for t in seed_transports(now, Random(7), OpsConfig()))
    return now
