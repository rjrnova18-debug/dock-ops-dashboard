"""
The live board's views: thin glue between HTTP, the database and dockops.

A view loads rows, turns them into dataclasses and hands them to dockops. It never
computes a business rule itself.
"""
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from board.conf import get_ops_config
from board.models import Transport, local_now
from dockops import live, rules


@require_GET
def board_page(request):
    """The live board page: a chassis of labels that board.js fills from board_data. Public."""
    return render(request, "board/board.html", {"refresh_seconds": settings.BOARD_REFRESH_SECONDS})


@require_GET
@never_cache            # the screen polls this: every answer must be fresh
def board_data(request):
    """The live board payload of API-CONTRACT.md, exactly as dockops builds it. Public."""
    config = get_ops_config()
    now = local_now()
    week_start, _week_end = rules.week_of(now.date(), config)
    transports = Transport.objects.relevant_to(week_start).to_domain()
    payload = live.build_live_payload(transports, now, config, Transport.objects.last_updated_at())
    return JsonResponse(payload)
