"""Tests for dockops.models: the small amount of behaviour the data classes have."""
from datetime import date, datetime, time

import pytest

from dockops.models import OpsConfig, Status, Transport


def test_config_rejects_a_break_outside_the_shift():
    with pytest.raises(ValueError):
        OpsConfig(shift_start=time(7), shift_end=time(21), break_start=time(6), break_end=time(8))


def test_config_rejects_a_break_that_ends_before_it_starts():
    with pytest.raises(ValueError):
        OpsConfig(break_start=time(14), break_end=time(13))


@pytest.mark.parametrize("status, expected", [
    (Status.SCHEDULED, False),
    (Status.LOADED, False),
    (Status.DISPATCHED, True),
    (Status.IN_TRANSIT, True),
    (Status.DELIVERED, True),
])
def test_is_dispatched(status, expected):
    assert Transport(number="T-1", status=status).is_dispatched is expected


@pytest.mark.parametrize("status, expected", [
    (Status.WAITING, False),       # in the yard, even with a bay assigned
    (Status.INSPECTED, True),
    (Status.LOADING, True),
    (Status.LOADED, True),
    (Status.DISPATCHED, False),
])
def test_is_at_bay(status, expected):
    assert Transport(number="T-1", status=status, bay=3).is_at_bay is expected


def test_appointment_day():
    transport = Transport(number="T-1", planned_arrival=datetime(2025, 3, 12, 9, 30))
    assert transport.appointment_day == date(2025, 3, 12)
    assert Transport(number="T-2").appointment_day is None
