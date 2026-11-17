"""The operation's configuration, read from settings.DOCKOPS."""
import pytest
from django.test import override_settings

from board.conf import get_ops_config
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
