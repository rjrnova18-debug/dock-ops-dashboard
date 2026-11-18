"""The operation's configuration: settings.DOCKOPS and the public holidays."""
from datetime import date

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.utils import timezone

from board.conf import get_ops_config, public_holidays
from dockops.models import OpsConfig


def test_without_overrides_the_demo_defaults_are_used():
    assert get_ops_config() == OpsConfig()


@override_settings(DOCKOPS={"bays": (1, 2, 3)})
def test_settings_change_only_what_they_name():
    config = get_ops_config()

    assert config.bays == (1, 2, 3)
    assert config.tolerance_minutes == OpsConfig().tolerance_minutes


@override_settings(DOCKOPS={"bay_count": 4})
def test_an_unknown_setting_fails_loudly():
    with pytest.raises(TypeError):
        get_ops_config()


# ------------------------------------------------------------------- Holidays

def test_without_a_country_there_are_no_holidays():
    assert public_holidays("", "", 2026) == frozenset()


def test_holidays_cover_four_years_back_and_one_ahead():
    us = public_holidays("US", "", 2026)

    assert date(2026, 7, 4) in us
    assert date(2022, 7, 4) in us and date(2027, 7, 4) in us
    assert date(2021, 7, 4) not in us and date(2028, 7, 4) not in us


def test_a_subdivision_adds_its_regional_holidays():
    patriots_day = date(2026, 4, 20)       # Massachusetts only

    assert patriots_day in public_holidays("US", "MA", 2026)
    assert patriots_day not in public_holidays("US", "", 2026)


@pytest.mark.parametrize("country, subdivision", [("XX", ""), ("US", "ZZ")])
def test_an_unknown_country_or_subdivision_fails_loudly(country, subdivision):
    with pytest.raises(ImproperlyConfigured):
        public_holidays(country, subdivision, 2026)


@override_settings(HOLIDAYS_COUNTRY="US")
def test_the_config_carries_the_holidays_of_the_settings_country():
    independence_day = date(timezone.localdate().year, 7, 4)

    assert independence_day in get_ops_config().holidays
