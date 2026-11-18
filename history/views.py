"""
The history's views: thin glue between HTTP, the database and dockops.history.

Everything here is private (HISTORY.md, "Access"): the page sends a visitor to sign in,
the data endpoints answer 401/403 as JSON and never redirect, and no answer is cached.
"""
from datetime import date
from functools import wraps
from typing import NamedTuple

from django.http import JsonResponse
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from board.conf import get_ops_config
from board.models import HISTORY_PERMISSION, Transport, local_now
from dockops import history
from dockops.models import CargoType

MAX_PERIOD_DAYS = 3 * 366          # "at most 3 years apart"


# ------------------------------------------------------------------- Access

def api_permission_required(view):
    """For data endpoints: 401 without a session, 403 without the permission, both as JSON."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": _("Sign in to see the history.")}, status=401)
        if not request.user.has_perm(HISTORY_PERMISSION):
            return JsonResponse({"error": _("Your account does not have access to the history.")}, status=403)
        return view(request, *args, **kwargs)
    return wrapper


# ------------------------------------------------------------------- Request

class HistoryRequest(NamedTuple):
    start: date
    end: date
    group_by: str
    cargo_type: CargoType | None


def read_request(query) -> HistoryRequest:
    """The parameters of HISTORY.md, "Request". Raises ValueError with a short message."""
    start = _read_day(query, "start")
    end = _read_day(query, "end")
    if end < start:
        raise ValueError(_("The end of the period is before its start."))
    if (end - start).days > MAX_PERIOD_DAYS:
        raise ValueError(_("The period can be at most 3 years long."))

    group_by = query.get("group_by") or "week"
    if group_by not in history.GROUPINGS:
        raise ValueError(_("group_by must be day, week or month."))

    cargo = query.get("cargo_type") or None
    if cargo not in (None, *(c.value for c in CargoType)):
        raise ValueError(_("cargo_type must be dry, cold or empty."))
    return HistoryRequest(start, end, group_by, CargoType(cargo) if cargo else None)


def _read_day(query, name: str) -> date:
    value = query.get(name)
    if not value:
        raise ValueError(_("The period is incomplete: %(name)s is missing.") % {"name": name})
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(_("%(name)s is not a date (expected YYYY-MM-DD).") % {"name": name}) from None


def _transports(params: HistoryRequest):
    """Every transport that may count in the period (HISTORY.md, "Loading the transports")."""
    return Transport.objects.relevant_to(params.start, params.end).to_domain()


# ------------------------------------------------------------------- Views

@require_GET
@never_cache
@api_permission_required
def history_data(request):
    """The history summary of API-CONTRACT.md, exactly as dockops builds it."""
    try:
        params = read_request(request.GET)
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)
    summary = history.build_history_summary(_transports(params), params.start, params.end, local_now(),
                                            get_ops_config(), params.group_by, params.cargo_type)
    return JsonResponse(summary)
