"""The live board: its public JSON endpoint and its page."""
import re
from datetime import datetime, timedelta
from pathlib import Path
from random import Random

import pytest
from django.contrib.staticfiles import finders
from django.test import override_settings
from django.urls import reverse

from board.demo import seed_transports
from board.models import Transport
from dockops.models import OpsConfig, Status
from dockops.models import Transport as DomainTransport

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 12, 10, 42)       # a Thursday
CONTRACT_KEYS = {"generated_at", "data_updated_at", "data_is_stale", "week", "status_chart",
                 "loading_chart", "cycle_chart", "adherence_chart", "bays", "incoming"}


@pytest.fixture
def fixed_now(monkeypatch):
    monkeypatch.setattr("board.views.local_now", lambda: NOW)


def save(*transports: DomainTransport) -> None:
    Transport.objects.bulk_create(Transport.from_domain(t) for t in transports)


def get_board(client):
    return client.get(reverse("board:data"))


def test_an_empty_board_answers_with_the_contract_shape(client, fixed_now):
    response = get_board(client)
    payload = response.json()

    assert response.status_code == 200
    assert set(payload) == CONTRACT_KEYS
    assert payload["generated_at"] == "2026-11-12T10:42:00"
    assert payload["data_updated_at"] is None
    assert payload["data_is_stale"] is True                 # unknown freshness is a warning (L11)
    assert [bay["bay"] for bay in payload["bays"]] == list(OpsConfig().bays)


def test_the_seeded_operation_shows_on_the_board(client, fixed_now):
    save(*seed_transports(NOW, Random(7), OpsConfig()))

    payload = get_board(client).json()

    assert payload["week"]["dispatched"] > 0
    assert any(bay["transports"] for bay in payload["bays"])
    assert payload["incoming"]


def test_an_old_transport_dispatched_this_week_counts(client, fixed_now):
    # Appointment far older than the lookback window, but it left on Monday of this week.
    save(DomainTransport(number="T-OLD", status=Status.DISPATCHED,
                         planned_arrival=NOW - timedelta(days=60), departed_at=NOW - timedelta(days=3)))

    assert get_board(client).json()["week"]["dispatched"] == 1


def test_the_answer_is_never_cached(client, fixed_now):
    assert "no-cache" in get_board(client)["Cache-Control"]


def test_only_get_is_allowed(client):
    assert client.post(reverse("board:data")).status_code == 405


# ------------------------------------------------------------------- The page

def test_the_root_address_opens_the_board_page(client):
    response = client.get("/")
    html = response.content.decode()

    assert response.status_code == 200
    assert f'data-url="{reverse("board:data")}"' in html
    assert 'data-refresh-seconds="30"' in html
    assert reverse("javascript-catalog") in html
    assert "board/board.js" in html


@override_settings(BOARD_REFRESH_SECONDS=45)
def test_the_refresh_interval_comes_from_the_settings(client):
    assert 'data-refresh-seconds="45"' in client.get("/").content.decode()


def test_the_javascript_catalog_is_served(client):
    response = client.get(reverse("javascript-catalog"))

    assert response.status_code == 200
    assert "gettext" in response.content.decode()


def test_every_font_named_by_the_stylesheet_is_in_the_repository():
    stylesheet = Path(finders.find("css/mecha.css"))
    fonts = re.findall(r'url\("([^"]+\.woff2)"\)', stylesheet.read_text(encoding="utf-8"))

    assert len(fonts) == 9
    assert all((stylesheet.parent / font).resolve().is_file() for font in fonts)
