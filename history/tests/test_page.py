"""The history page: who may open it, and the chassis it serves."""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

PAGE = reverse("history:page")


def test_without_a_session_the_page_sends_the_visitor_to_sign_in_and_back(client):
    response = client.get(PAGE)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={PAGE}"


def test_without_the_permission_the_page_says_no_access(client, outsider):
    client.force_login(outsider)

    response = client.get(PAGE)

    assert response.status_code == 403
    assert "No access" in response.content.decode()
    assert "Sign in as someone else" in response.content.decode()


def test_a_viewer_gets_the_chassis(client, viewer):
    client.force_login(viewer)

    html = client.get(PAGE).content.decode()

    assert f'data-url="{reverse("history:data")}"' in html
    assert f'data-csv-url="{reverse("history:csv")}"' in html
    assert "history/history.js" in html
    assert html.count('class="panel cut chart-card"') == 5
    assert "viewer" in html                                   # the signed-in user's name


def test_signing_in_without_a_destination_opens_the_history(client, viewer):
    response = client.post(reverse("login"), {"username": "viewer", "password": "a-long-demo-password"})

    assert response["Location"] == PAGE
