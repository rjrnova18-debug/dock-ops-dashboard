"""Project-wide views: the error pages that are not tied to one app."""
from django.http import JsonResponse
from django.views.defaults import page_not_found


def not_found(request, exception):
    """
    "Not found" is a page for a person browsing, and plain JSON for a data endpoint,
    because a script reading /api/... cannot do anything with HTML.
    """
    if request.path.startswith("/api/"):
        return JsonResponse({"error": "Not found."}, status=404)
    return page_not_found(request, exception)      # renders templates/404.html
