"""
Running the demo simulator against the database.

demo.advance() decides what happens; this module loads the transports it needs, calls
it and saves what changed. The simulate command, the admin and the automatic mode all
go through run_step().
"""
import random
from datetime import datetime, timedelta

from django.db import transaction

from board import demo
from board.conf import get_ops_config
from board.models import Transport


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
