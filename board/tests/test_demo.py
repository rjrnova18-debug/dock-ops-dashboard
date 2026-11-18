"""
The demo seed: every case of DEMO-DATA.md must show on the live board, at any hour.

The cases are checked through the real live board payload, so "a loading at the
critical level" means what the board would actually display.
"""
from datetime import date, datetime, timedelta
from io import StringIO
from random import Random

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings

from board import demo
from board.demo import seed_transports
from board.models import Transport
from dockops import live
from dockops.models import OpsConfig, Status

CONFIG = OpsConfig()
THURSDAY = datetime(2026, 11, 12, 10, 42)
NOWS = {
    "thursday morning": THURSDAY,
    "during the break": datetime(2026, 11, 12, 13, 30),
    "monday after midnight": datetime(2026, 11, 9, 0, 20),
    "monday shift start": datetime(2026, 11, 9, 7, 5),
    "saturday night": datetime(2026, 11, 14, 22, 30),
    "sunday (rest day)": datetime(2026, 11, 15, 10, 0),
}
any_hour = pytest.mark.parametrize("now", NOWS.values(), ids=NOWS.keys())

# How many actual times each status has: arrival, inspection, loading start, loading end, departure.
TIMES_PER_STATUS = {
    Status.SCHEDULED: 0, Status.WAITING: 1, Status.INSPECTED: 2, Status.LOADING: 3, Status.LOADED: 4,
    Status.DISPATCHED: 5, Status.IN_TRANSIT: 5, Status.DELIVERED: 5,
}


def seed(now: datetime, config: OpsConfig = CONFIG, number: int = 7):
    transports = seed_transports(now, Random(number), config)
    return transports, live.build_live_payload(transports, now, config, now)


def at_bay(payload: dict) -> list[dict]:
    return [row for bay in payload["bays"] for row in bay["transports"]]


# ------------------------------------------------------------------- Today's board

@any_hour
def test_every_timer_level_shows(now):
    _, payload = seed(now)
    loading = [row["timer"] for row in at_bay(payload) if row["timer"]["state"] in ("running", "paused")]

    assert {timer["level"] for timer in loading} == {"ok", "warning", "critical"}


@any_hour
def test_a_cold_loading_is_ok_against_its_own_average_but_over_the_dry_one(now):
    _, payload = seed(now)
    dry_average = payload["loading_chart"]["by_cargo_type"]["dry"]["week_average"]

    assert any(row["cargo_type"] == "cold" and row["timer"]["level"] == "ok"
               and row["timer"]["elapsed_seconds"] / 60 >= dry_average for row in at_bay(payload))


@any_hour
def test_finished_and_not_started_timers_show(now):
    _, payload = seed(now)
    states = {row["timer"]["state"] for row in at_bay(payload)}

    assert {"finished", "not_started"} <= states


@any_hour
def test_two_bays_are_free_and_a_waiting_transport_does_not_occupy_its_bay(now):
    _, payload = seed(now)
    free = {bay["bay"] for bay in payload["bays"] if bay["is_configured"] and not bay["transports"]}
    assigned = [row for row in payload["incoming"] if row["status"] == "waiting" and row["bay"] is not None]

    assert len(free) >= 2
    assert assigned and all(row["bay"] in free for row in assigned)


@any_hour
def test_the_incoming_list_has_every_group_and_late_arrivals_first(now):
    _, payload = seed(now)
    incoming = payload["incoming"]

    assert {row["group"] for row in incoming} >= {"waiting", "earlier", "today", "tomorrow"}
    assert incoming[0]["is_late"]
    assert any(row["status"] == "waiting" and row["arrival_outcome"] == "late" for row in incoming)


@any_hour
def test_an_appointment_two_days_ahead_exists_but_is_not_listed(now):
    transports, payload = seed(now)
    two_days_ahead = [t.number for t in transports if t.appointment_day == now.date() + timedelta(days=2)]

    assert two_days_ahead
    assert not set(two_days_ahead) & {row["number"] for row in payload["incoming"]}


@any_hour
def test_the_carryovers_show(now):
    transports, payload = seed(now)
    today = now.date()

    assert any(row["is_carryover"] and row["departure_overdue"] for row in at_bay(payload))
    assert any(row["group"] == "earlier" and row["status"] == "scheduled" for row in payload["incoming"])
    assert any(t.is_dispatched and t.appointment_day < today and t.departed_at.date() == today
               for t in transports)


@any_hour
def test_every_visit_that_loaded_went_through_a_bay(now):
    transports, payload = seed(now)

    assert all(row["bay"] is not None for row in payload["week"]["completed"])
    assert all(t.bay in CONFIG.bays for t in transports if t.loading_started_at)


@any_hour
def test_transports_were_dispatched_today(now):
    _, payload = seed(now)

    assert any(row["departed_at"].startswith(now.date().isoformat()) for row in payload["week"]["completed"])


# ------------------------------------------------------------------- Coherence

@any_hour
def test_each_visit_follows_its_order_and_matches_its_status(now):
    transports, _ = seed(now)

    for t in transports:
        actual = [t.arrived_at, t.inspected_at, t.loading_started_at, t.loading_ended_at, t.departed_at]
        happened = [moment for moment in actual if moment is not None]
        assert actual[:len(happened)] == happened, t.number          # no gaps
        assert happened == sorted(happened), t.number                 # in the order of a visit
        assert all(moment <= now for moment in happened), t.number    # nothing in the future
        assert len(happened) == TIMES_PER_STATUS[t.status], t.number


def test_the_same_seed_at_the_same_moment_gives_the_same_data():
    first = seed_transports(THURSDAY, Random(7), CONFIG)

    assert first == seed_transports(THURSDAY, Random(7), CONFIG)
    assert first != seed_transports(THURSDAY, Random(8), CONFIG)


def test_transport_numbers_are_unique():
    numbers = [t.number for t in seed_transports(THURSDAY, Random(7), CONFIG)]

    assert len(numbers) == len(set(numbers))


def test_roughly_a_third_of_the_transports_are_cold():
    transports = seed_transports(THURSDAY, Random(7), CONFIG)
    cold_share = sum(t.cargo_type.value == "cold" for t in transports) / len(transports)

    assert 0.2 < cold_share < 0.45


def test_the_seed_never_fills_more_than_all_but_two_bays():
    _, payload = seed(THURSDAY, OpsConfig(bays=(1, 2, 3, 4)))
    occupied = [bay for bay in payload["bays"] if bay["transports"]]

    assert len(occupied) == 2
    assert all(bay["is_configured"] for bay in occupied)


# ------------------------------------------------------------------- History

def test_history_has_no_visits_on_rest_days_or_holidays():
    holiday = date(2026, 11, 4)                        # a Wednesday
    config = OpsConfig(holidays=frozenset({holiday}))
    transports = seed_transports(THURSDAY, Random(7), config)
    before_the_scenario = THURSDAY.date() - timedelta(days=2)
    history_days = {t.loading_ended_at.date() for t in transports
                    if t.loading_ended_at and t.loading_ended_at.date() < before_the_scenario}

    assert len(history_days) > 50
    assert holiday not in history_days
    assert all(day.weekday() != 6 for day in history_days)


def test_history_has_unclosed_transports_and_missing_plans():
    transports = seed_transports(THURSDAY, Random(7), CONFIG)
    too_old = THURSDAY.date() - timedelta(days=CONFIG.carryover_days)
    unclosed = [t for t in transports if not t.is_dispatched and t.appointment_day and t.appointment_day < too_old]

    assert len(unclosed) == len(demo.UNCLOSED_DAYS_AGO)
    assert any(t.loading_started_at and t.planned_loading_start is None for t in transports)


# ------------------------------------------------------------------- The command

@pytest.mark.django_db
@override_settings(DEMO_USER_PASSWORD="a-long-demo-password")
def test_seed_demo_creates_a_demo_user_who_can_only_see_the_history(django_user_model):
    call_command("seed_demo", "--seed", "7", stdout=StringIO())
    call_command("seed_demo", "--seed", "7", stdout=StringIO())      # running it again keeps one user

    demo_user = django_user_model.objects.get(username="demo")
    assert demo_user.check_password("a-long-demo-password")
    assert demo_user.has_perm("board.view_history")
    assert not demo_user.is_staff and not demo_user.is_superuser
    assert django_user_model.objects.filter(username="demo").count() == 1


@pytest.mark.django_db
def test_without_a_demo_password_there_is_no_demo_user(django_user_model):
    call_command("seed_demo", "--seed", "7", stdout=StringIO())

    assert not django_user_model.objects.filter(username="demo").exists()


@pytest.mark.django_db
@override_settings(DEMO_USER_PASSWORD="short")
def test_a_weak_demo_password_is_refused():
    with pytest.raises(CommandError, match="DEMO_USER_PASSWORD"):
        call_command("seed_demo", "--seed", "7", stdout=StringIO())


@pytest.mark.django_db
def test_seed_demo_replaces_every_transport():
    call_command("seed_demo", "--seed", "7", stdout=StringIO())
    first_count = Transport.objects.count()
    call_command("seed_demo", "--seed", "7", stdout=StringIO())

    assert Transport.objects.count() == first_count > 0
    assert Transport.objects.last_updated_at() is not None
