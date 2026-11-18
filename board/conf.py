"""
The operation's configuration for this deployment.

settings.DOCKOPS holds only what differs from the demo defaults of dockops.OpsConfig,
for example {"bays": (1, 2, 3, 4)}. An unknown name or an invalid shift fails loudly.

Public holidays come from the `holidays` package, for the country (and optional
subdivision) in settings.HOLIDAYS_COUNTRY / HOLIDAYS_SUBDIVISION. dockops never sees the
package: it receives a plain set of dates and treats each one like the rest day.
"""
from datetime import date
from functools import cache

import holidays
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from dockops.models import OpsConfig

# The history reports periods of up to 3 years, plus the days loaded before them.
YEARS_BACK = 4
YEARS_AHEAD = 1


def get_ops_config() -> OpsConfig:
    holiday_dates = public_holidays(settings.HOLIDAYS_COUNTRY, settings.HOLIDAYS_SUBDIVISION,
                                    timezone.localdate().year)
    # Anything in DOCKOPS wins, including an explicit "holidays".
    return OpsConfig(**({"holidays": holiday_dates} | getattr(settings, "DOCKOPS", {})))


@cache
def public_holidays(country: str, subdivision: str, year: int) -> frozenset[date]:
    """
    The public holidays from YEARS_BACK years before `year` to YEARS_AHEAD after it.

    An empty country means no holidays. The result is a fixed set: the package's own
    calendar object adds years on demand, which a rule should never trigger by accident.
    """
    if not country:
        return frozenset()
    years = range(year - YEARS_BACK, year + YEARS_AHEAD + 1)
    try:
        calendar = holidays.country_holidays(country, subdiv=subdivision or None, years=years, expand=False)
    except NotImplementedError as error:
        raise ImproperlyConfigured(f"Check HOLIDAYS_COUNTRY / HOLIDAYS_SUBDIVISION: {error}") from error
    return frozenset(calendar.keys())
