"""Sign-in protections and the site-wide error pages (HISTORY.md, "Access"; UI-BRIEF section 5)."""
import time

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import reverse

from config.middleware import SIGNED_IN_AT

pytestmark = pytest.mark.django_db

LOGIN = reverse("login")
PASSWORD = "a-long-demo-password"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("ana", password=PASSWORD)


def sign_in(client, password, address="10.0.0.1"):
    return client.post(LOGIN, {"username": "ana", "password": password}, REMOTE_ADDR=address)


# ------------------------------------------------------------------- Sign in and out

def test_the_sign_in_page_keeps_where_the_user_was_going(client):
    html = client.get(f"{LOGIN}?next=/history/").content.decode()

    assert 'value="/history/"' in html
    assert "csrfmiddlewaretoken" in html
    assert reverse("board:page") in html


def test_signing_in_brings_the_user_back(client, user):
    response = client.post(LOGIN, {"username": "ana", "password": PASSWORD, "next": "/history/"})

    assert response.status_code == 302 and response["Location"] == "/history/"


def test_wrong_credentials_show_a_message(client, user):
    response = sign_in(client, "wrong-password")

    assert response.status_code == 200
    assert "Wrong user name or password" in response.content.decode()


def test_signing_out_needs_a_post(client, user):
    client.force_login(user)

    assert client.get(reverse("logout")).status_code == 405
    assert client.post(reverse("logout")).status_code == 302


def test_passwords_need_twelve_characters():
    with pytest.raises(ValidationError):
        validate_password("short-pass")
    validate_password("long-enough-passphrase")


# ------------------------------------------------------------------- Temporary lock (django-axes)

def test_five_failures_lock_the_user_from_that_address(client, user):
    for _ in range(5):
        sign_in(client, "wrong-password")

    locked = sign_in(client, PASSWORD)                 # even the right password is refused now

    assert locked.status_code == 429
    assert "paused" in locked.content.decode()


def test_the_lock_does_not_affect_the_same_user_from_another_address(client, user):
    for _ in range(5):
        sign_in(client, "wrong-password", address="10.0.0.1")

    assert sign_in(client, PASSWORD, address="10.0.0.2").status_code == 302


# ------------------------------------------------------------------- Sessions

def test_sessions_expire_after_thirty_minutes_without_activity(settings):
    assert settings.SESSION_COOKIE_AGE == 30 * 60
    assert settings.SESSION_SAVE_EVERY_REQUEST is True


def test_a_session_remembers_when_it_signed_in(client, user):
    client.force_login(user)
    client.get("/")

    assert "_auth_user_id" in client.session
    assert SIGNED_IN_AT in client.session


def test_a_session_older_than_eight_hours_is_signed_out(client, user):
    client.force_login(user)
    session = client.session
    session[SIGNED_IN_AT] = int(time.time()) - 9 * 60 * 60
    session.save()

    client.get("/")

    assert "_auth_user_id" not in client.session


# ------------------------------------------------------------------- Error pages

def test_not_found_is_a_page_for_people(client):
    response = client.get("/no/such/page/")

    assert response.status_code == 404
    assert "/no/such/page/" in response.content.decode()
    assert reverse("board:page") in response.content.decode()


def test_not_found_is_plain_json_for_data_endpoints(client):
    response = client.get("/api/no-such-endpoint/")

    assert response.status_code == 404
    assert response.json() == {"error": "Not found."}


def test_the_no_access_page_offers_to_sign_in():
    request = RequestFactory().get("/history/")
    request.user = AnonymousUser()

    html = render_to_string("403.html", request=request)

    assert f"{LOGIN}?next=/history/" in html
