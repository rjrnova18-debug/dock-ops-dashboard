"""The transport admin and its simulation button."""
import pytest
from django.urls import reverse

from board.models import Transport

pytestmark = pytest.mark.django_db

CHANGELIST = reverse("admin:board_transport_changelist")
SIMULATE = reverse("admin:board_transport_simulate")


@pytest.fixture
def steps(monkeypatch):
    """Record the simulation steps instead of running them; each one 'changes' 3 transports."""
    calls = []
    monkeypatch.setattr("board.simulator.run_step", lambda now: calls.append(now) or 3)
    return calls


def test_the_transport_list_shows_the_simulation_button(admin_client):
    Transport.objects.create(number="T-1")

    html = admin_client.get(CHANGELIST).content.decode()

    assert "T-1" in html
    assert f'action="{SIMULATE}"' in html


def test_a_transport_can_be_opened_in_the_admin(admin_client):
    transport = Transport.objects.create(number="T-1")

    assert admin_client.get(reverse("admin:board_transport_change", args=[transport.pk])).status_code == 200


def test_the_button_runs_one_step_and_reports_it(admin_client, steps):
    response = admin_client.post(SIMULATE, follow=True)

    assert len(steps) == 1
    assert response.redirect_chain[-1][0] == CHANGELIST
    assert "3 transports changed" in response.content.decode()


def test_opening_the_simulation_address_does_not_step(admin_client, steps):
    response = admin_client.get(SIMULATE)

    assert response.status_code == 302 and steps == []


def test_only_staff_can_run_the_simulation(client, steps):
    response = client.post(SIMULATE)

    assert response.status_code == 302 and "login" in response["Location"]
    assert steps == []
