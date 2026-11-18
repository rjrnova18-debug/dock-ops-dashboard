"""The demo simulator: one step of the operation, and running it against the database."""
from datetime import datetime, timedelta
from io import StringIO
from random import Random

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from board.demo import MIN_UPCOMING, advance, own_pace, seed_transports
from board.models import Transport
from board.simulator import LOCK_KEY, run_automatic_step_if_due, run_step
from dockops.models import OpsConfig, Status
from dockops.models import Transport as DomainTransport

CONFIG = OpsConfig()
THURSDAY = datetime(2026, 11, 12, 10, 42)

STAGE = {Status.SCHEDULED: 0, Status.WAITING: 1, Status.INSPECTED: 2, Status.LOADING: 3, Status.LOADED: 4,
         Status.DISPATCHED: 5, Status.IN_TRANSIT: 6, Status.DELIVERED: 7}
TIME_OF_MOVE = {Status.WAITING: "arrived_at", Status.INSPECTED: "inspected_at", Status.LOADING: "loading_started_at",
                Status.LOADED: "loading_ended_at", Status.DISPATCHED: "departed_at"}
TIMES_PER_STATUS = {Status.SCHEDULED: 0, Status.WAITING: 1, Status.INSPECTED: 2, Status.LOADING: 3, Status.LOADED: 4,
                    Status.DISPATCHED: 5, Status.IN_TRANSIT: 5, Status.DELIVERED: 5}


def apply(transports: list[DomainTransport], changed: list[DomainTransport]) -> list[DomainTransport]:
    """What the database holds after saving a step."""
    by_number = {t.number: t for t in transports}
    by_number.update({t.number: t for t in changed})
    return list(by_number.values())


@pytest.fixture
def seeded() -> list[DomainTransport]:
    return seed_transports(THURSDAY, Random(7), CONFIG)


def upcoming(transports, now) -> int:
    return sum(t.status is Status.SCHEDULED and t.planned_arrival and t.planned_arrival > now for t in transports)


# ------------------------------------------------------------------- One step

def test_each_transport_moves_one_stage_and_records_when(seeded):
    before = {t.number: t for t in seeded}
    now = THURSDAY + timedelta(minutes=2)

    moved = [t for t in advance(seeded, now, Random(1), CONFIG) if t.number in before]

    assert moved
    for t in moved:
        assert STAGE[t.status] == STAGE[before[t.number].status] + 1, t.number
        if t.status in TIME_OF_MOVE:
            assert getattr(t, TIME_OF_MOVE[t.status]) == now, t.number


def test_new_appointments_have_new_numbers(seeded):
    old_numbers = {t.number for t in seeded}
    highest = max(int(n.split("-")[1]) for n in old_numbers)

    new = [t for t in advance(seeded, THURSDAY, Random(1), CONFIG) if t.number not in old_numbers]

    assert new
    assert all(t.status is Status.SCHEDULED and int(t.number.split("-")[1]) > highest for t in new)
    assert len({t.number for t in new}) == len(new)


def test_the_same_seed_gives_the_same_step(seeded):
    assert advance(seeded, THURSDAY, Random(3), CONFIG) == advance(seeded, THURSDAY, Random(3), CONFIG)


@pytest.mark.parametrize("now, config", [
    (datetime(2026, 11, 14, 23, 0), CONFIG),                                          # after the shift
    (datetime(2026, 11, 15, 10, 0), CONFIG),                                          # Sunday
    (THURSDAY, OpsConfig(holidays=frozenset({THURSDAY.date()}))),                     # a holiday
], ids=["after the shift", "rest day", "holiday"])
def test_outside_working_time_only_the_road_and_the_planning_go_on(seeded, now, config):
    before = {t.number: t for t in seeded}

    for t in advance(seeded, now, Random(1), config):
        if t.number in before:
            assert t.status in (Status.IN_TRANSIT, Status.DELIVERED), t.number
        else:
            assert t.status is Status.SCHEDULED


def test_a_loading_ends_when_it_reaches_its_own_pace():
    now = datetime(2026, 11, 12, 11, 0)
    done = DomainTransport(number="T-1", status=Status.LOADING, bay=1)
    done.loading_started_at = now - timedelta(minutes=own_pace(done) + 1)
    halfway = DomainTransport(number="T-2", status=Status.LOADING, bay=2)
    halfway.loading_started_at = now - timedelta(minutes=own_pace(halfway) / 2)

    changed = {t.number: t for t in advance([done, halfway], now, Random(1), CONFIG)}

    assert changed["T-1"].status is Status.LOADED and changed["T-1"].loading_ended_at == now
    assert changed["T-1"].seal_number
    assert "T-2" not in changed


def test_a_working_day_stays_coherent():
    now = datetime(2026, 11, 12, 7, 0)
    transports = seed_transports(now, Random(7), CONFIG)        # seeded at the moment the day starts
    dispatched_before = sum(t.status is Status.DISPATCHED for t in transports)
    rng = Random(5)

    for _ in range(7 * 30):                                  # 7 hours, one step every 2 minutes
        now += timedelta(minutes=2)
        transports = apply(transports, advance(transports, now, rng, CONFIG))
        bays = [t.bay for t in transports if t.is_at_bay]
        assert len(bays) == len(set(bays)) and set(bays) <= set(CONFIG.bays)

    for t in transports:
        actual = [t.arrived_at, t.inspected_at, t.loading_started_at, t.loading_ended_at, t.departed_at]
        happened = [m for m in actual if m is not None]
        assert actual[:len(happened)] == happened and happened == sorted(happened), t.number
        assert len(happened) == TIMES_PER_STATUS[t.status], t.number
    assert sum(t.is_dispatched for t in transports) > dispatched_before
    assert upcoming(transports, now) >= MIN_UPCOMING


# ------------------------------------------------------------------- Against the database

@pytest.mark.django_db
def test_run_step_updates_rows_in_place_and_adds_new_ones(seeded):
    Transport.objects.bulk_create(Transport.from_domain(t) for t in seeded)
    count_before = Transport.objects.count()

    changes = run_step(THURSDAY + timedelta(minutes=2), Random(1))

    assert changes > 0
    assert Transport.objects.count() >= count_before
    assert Transport.objects.values("number").distinct().count() == Transport.objects.count()


@pytest.fixture
def empty_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_the_automatic_mode_is_off_by_default(seeded, empty_cache):
    Transport.objects.bulk_create(Transport.from_domain(t) for t in seeded)

    assert run_automatic_step_if_due(THURSDAY) is False


@pytest.mark.django_db
@override_settings(SIMULATOR_AUTO=True)
def test_the_automatic_mode_steps_once_per_gap(seeded, empty_cache):
    Transport.objects.bulk_create(Transport.from_domain(t) for t in seeded)

    assert run_automatic_step_if_due(THURSDAY) is True
    assert run_automatic_step_if_due(THURSDAY + timedelta(seconds=30)) is False      # not due yet
    assert run_automatic_step_if_due(THURSDAY + timedelta(seconds=121)) is True      # the gap is 60-120 s


@pytest.mark.django_db
@override_settings(SIMULATOR_AUTO=True)
def test_a_request_that_finds_the_lock_taken_does_not_step(seeded, empty_cache):
    cache.add(LOCK_KEY, True)                        # another request is stepping right now

    assert run_automatic_step_if_due(THURSDAY) is False


@pytest.mark.django_db
def test_the_board_request_gives_the_automatic_mode_its_chance(client, monkeypatch):
    calls = []
    monkeypatch.setattr("board.views.local_now", lambda: THURSDAY)
    monkeypatch.setattr("board.simulator.run_automatic_step_if_due", calls.append)

    client.get(reverse("board:data"))

    assert calls == [THURSDAY]


@pytest.mark.django_db
def test_the_simulate_command_reports_its_steps():
    call_command("seed_demo", "--seed", "7", stdout=StringIO())
    out = StringIO()

    call_command("simulate", "--steps", "2", "--seed", "1", stdout=out)

    assert "2 step(s)" in out.getvalue()
