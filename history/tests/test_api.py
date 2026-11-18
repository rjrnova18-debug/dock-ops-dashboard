"""The private JSON endpoint of the history (HISTORY.md "Access" and "Request")."""
import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from board.models import HISTORY_VIEWERS_GROUP

pytestmark = pytest.mark.django_db

URL = reverse("history:data")
NOVEMBER = {"start": "2026-11-01", "end": "2026-11-30"}
CONTRACT_KEYS = {"period_start", "period_end", "group_by", "cargo_type", "generated_at", "totals", "by_cargo_type",
                 "series", "checkpoints", "activity", "slowest_loadings", "fastest_loadings", "unclosed"}


def test_the_migration_creates_the_viewers_group_with_the_permission():
    group = Group.objects.get(name=HISTORY_VIEWERS_GROUP)

    assert list(group.permissions.values_list("codename", flat=True)) == ["view_history"]


# ------------------------------------------------------------------- Access

def test_without_a_session_it_answers_401_as_json(client):
    response = client.get(URL, NOVEMBER)

    assert response.status_code == 401
    assert "error" in response.json()


def test_without_the_permission_it_answers_403_as_json(client, outsider):
    client.force_login(outsider)

    response = client.get(URL, NOVEMBER)

    assert response.status_code == 403
    assert "error" in response.json()


def test_a_viewer_gets_the_summary(client, viewer, seeded):
    client.force_login(viewer)

    response = client.get(URL, NOVEMBER)
    summary = response.json()

    assert response.status_code == 200
    assert set(summary) == CONTRACT_KEYS
    assert summary["period_start"] == "2026-11-01" and summary["group_by"] == "week"
    assert summary["totals"]["appointments"] > 0
    assert len(summary["activity"]) == 30
    assert "no-cache" in response["Cache-Control"]


def test_the_filters_reach_dockops(client, viewer, seeded):
    client.force_login(viewer)

    summary = client.get(URL, {**NOVEMBER, "group_by": "day", "cargo_type": "cold"}).json()

    assert summary["group_by"] == "day" and summary["cargo_type"] == "cold"
    assert summary["by_cargo_type"]["dry"]["appointments"] == 0


# ------------------------------------------------------------------- Invalid requests

@pytest.mark.parametrize("params, words", [
    ({"end": "2026-11-30"}, "incomplete"),
    ({"start": "2026-11-30", "end": "2026-11-01"}, "before its start"),
    ({"start": "2020-01-01", "end": "2026-11-30"}, "3 years"),
    ({"start": "2026-11-01", "end": "30/11/2026"}, "not a date"),
    ({**NOVEMBER, "group_by": "year"}, "group_by"),
    ({**NOVEMBER, "cargo_type": "frozen"}, "cargo_type"),
], ids=["missing start", "end before start", "too long", "bad date", "bad grouping", "bad cargo type"])
def test_an_invalid_request_answers_400_saying_what_is_wrong(client, viewer, params, words):
    client.force_login(viewer)

    response = client.get(URL, params)

    assert response.status_code == 400
    assert words in response.json()["error"]
