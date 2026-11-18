"""
Site-wide middleware.

Django expires a session after inactivity (SESSION_COOKIE_AGE with SESSION_SAVE_EVERY_REQUEST)
but has no absolute limit: a session used every few minutes would live forever. This adds
one: settings.SESSION_MAX_AGE_SECONDS after sign-in, the user is signed out.
"""
import time

from django.conf import settings
from django.contrib.auth import logout

SIGNED_IN_AT = "signed_in_at"


class SessionMaxAgeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Signing in starts a fresh session, so the first request after it sets the time.
            signed_in_at = request.session.setdefault(SIGNED_IN_AT, int(time.time()))
            if time.time() - signed_in_at > settings.SESSION_MAX_AGE_SECONDS:
                logout(request)
        return self.get_response(request)
