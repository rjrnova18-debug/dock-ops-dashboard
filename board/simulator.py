"""
Running the demo simulator against the database.

demo.advance() decides what happens; this module loads the transports it needs, calls
it and saves what changed. The simulate command, the admin and the automatic mode all
go through run_step().
"""
import random
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from board import demo
from board.conf import get_ops_config
from board.models import Transport

AUTO_GAP_SECONDS = (60, 120)            # DEMO-DATA: the operation advances every 1 to 2 minutes
LOCK_KEY = "simulator:lock"
NEXT_STEP_KEY = "simulator:next-step-at"


def run_step(now: datetime, rng: random.Random | None = None) -> int:
    """Advance the operation one step at `now` (local time). Returns how many transports changed."""
    # Everything a step can touch: the board window, recent departures and the newest numbers.
    rows = {row.number: row for row in Transport.objects.relevant_to(now.date() - timedelta(days=2))}
    changed = demo.advance([row.to_domain() for row in rows.values()], now, rng or random.Random(), get_ops_config())
    with transaction.atomic():
        for transport in changed:
            row = rows.get(transport.number) or Transport()
            row.apply_domain(transport)
            row.save()      # save(), not bulk_update(): auto_now marks the board's "last update"
    return len(changed)


def run_automatic_step_if_due(now: datetime) -> bool:
    """
    The automatic mode (settings.SIMULATOR_AUTO): run one step when the next one is due.

    It is called from the board's data request (a "lazy tick"), so the deployed demo needs
    no extra process: while nobody watches nothing moves, and nothing is lost by that.
    The cache lock makes two screens asking at the same moment run the step only once.
    Returns whether a step ran.
    """
    if not settings.SIMULATOR_AUTO:
        return False
    next_step_at = cache.get(NEXT_STEP_KEY)
    if next_step_at is not None and now < next_step_at:
        return False
    if not cache.add(LOCK_KEY, True, timeout=60):    # add() only succeeds if nobody holds the lock
        return False
    try:
        run_step(now)
        cache.set(NEXT_STEP_KEY, now + timedelta(seconds=random.randint(*AUTO_GAP_SECONDS)), timeout=None)
        return True
    finally:
        cache.delete(LOCK_KEY)
