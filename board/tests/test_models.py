"""The Transport model: the bridge to dockops, the time zone and the loader."""
from datetime import UTC, date, datetime, time, timedelta

import pytest
from django.contrib.auth.models import Permission
from django.test import override_settings

from board.models import CARGO_TYPE_CHOICES, STATUS_CHOICES, Transport, to_local_naive
from dockops import history, live
from dockops.models import CargoType, Status
from dockops.models import Transport as DomainTransport

pytestmark = pytest.mark.django_db

# UTC+9 all year (no daylight saving), so the conversion is easy to check by hand.
TOKYO = "Asia/Tokyo"

START, END = date(2026, 11, 9), date(2026, 11, 15)


def save(number: str = "T-1", **fields) -> Transport:
    """Store a transport the way the seed will: from a dockops dataclass."""
    row = Transport.from_domain(DomainTransport(number=number, **fields))
    row.save()
    return row


def at(day: date, hour: int = 10, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute))


def numbers(queryset) -> list[str]:
    return sorted(transport.number for transport in queryset)


# ------------------------------------------------------------------- Bridge

def test_choices_follow_the_domain_enums():
    assert [value for value, _label in STATUS_CHOICES] == [status.value for status in Status]
    assert [value for value, _label in CARGO_TYPE_CHOICES] == [cargo.value for cargo in CargoType]


@override_settings(TIME_ZONE=TOKYO)
def test_a_transport_survives_the_round_trip_unchanged():
    day = date(2026, 11, 12)
    original = DomainTransport(
        number="T-1042", status=Status.LOADING, cargo_type=CargoType.COLD, bay=3,
        planned_arrival=at(day, 8), arrived_at=at(day, 8, 5), inspected_at=at(day, 8, 20),
        planned_loading_start=at(day, 9), loading_started_at=at(day, 9, 10),
        planned_loading_end=at(day, 12), loading_ended_at=None,
        planned_departure=at(day, 13), departed_at=None,
        carrier="Northwind Haulage", planner="A. Rowan", destination="Port Aster",
        booking_ref="BK-1001", seal_number="S-77", notes="Pre-cool the trailer",
    )
    Transport.from_domain(original).save()

    assert Transport.objects.get(number="T-1042").to_domain() == original


@override_settings(TIME_ZONE=TOKYO)
def test_local_times_are_stored_in_utc():
    save(planned_arrival=datetime(2026, 11, 12, 8, 0))

    assert Transport.objects.get().planned_arrival == datetime(2026, 11, 11, 23, 0, tzinfo=UTC)


def test_empty_fields_stay_empty():
    save("T-1")

    assert Transport.objects.get().to_domain() == DomainTransport(number="T-1")


def test_queryset_to_domain_returns_dataclasses():
    save("T-1")

    assert Transport.objects.all().to_domain() == [DomainTransport(number="T-1")]


def test_the_history_permission_exists():
    assert Permission.objects.filter(content_type__app_label="board", codename="view_history").exists()


# ------------------------------------------------------------------- Loader

def test_live_board_and_history_use_the_same_lookback():
    assert live.LOOKBACK_DAYS == history.LOOKBACK_DAYS


def test_appointments_are_loaded_from_the_lookback_window_to_the_end():
    save("first-day-of-window", planned_arrival=at(START - timedelta(days=live.LOOKBACK_DAYS)))
    save("too-old", planned_arrival=at(START - timedelta(days=live.LOOKBACK_DAYS + 1)))
    save("last-day", planned_arrival=at(END))
    save("after-the-end", planned_arrival=at(END + timedelta(days=1)))

    assert numbers(Transport.objects.relevant_to(START, END)) == ["first-day-of-window", "last-day"]


def test_without_an_end_there_is_no_upper_limit():
    save("next-month", planned_arrival=at(END + timedelta(days=30)))

    assert numbers(Transport.objects.relevant_to(START)) == ["next-month"]


def test_an_old_transport_is_loaded_when_it_arrives_or_departs_in_the_period():
    long_ago = at(START - timedelta(days=60))
    save("arrived", planned_arrival=long_ago, arrived_at=at(START))
    save("departed", planned_arrival=long_ago, departed_at=at(END))
    save("departed-before", planned_arrival=long_ago, departed_at=at(START - timedelta(days=1)))

    assert numbers(Transport.objects.relevant_to(START, END)) == ["arrived", "departed"]


def test_a_transport_without_an_appointment_is_always_loaded():
    save("no-appointment")

    assert numbers(Transport.objects.relevant_to(START, END)) == ["no-appointment"]


@override_settings(TIME_ZONE=TOKYO)
def test_days_are_the_operations_local_days():
    # 00:30 in Tokyo on the 16th is still the 15th in UTC: it must not count as the 15th.
    save("last-day", planned_arrival=at(END, 0, 30))
    save("day-after", planned_arrival=at(END + timedelta(days=1), 0, 30))

    assert numbers(Transport.objects.relevant_to(START, END)) == ["last-day"]


# ------------------------------------------------------------------- Last update

def test_last_updated_at_is_none_without_data():
    assert Transport.objects.last_updated_at() is None


@override_settings(TIME_ZONE=TOKYO)
def test_last_updated_at_is_the_newest_change_in_local_time():
    first, second = save("T-1"), save("T-2")

    newest = Transport.objects.last_updated_at()

    assert newest.tzinfo is None
    assert newest == to_local_naive(max(first.updated_at, second.updated_at))
