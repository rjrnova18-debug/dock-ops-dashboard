"""
Invented demo data, as pure functions: no database, no clock.

seed_transports() builds a whole operation around `now`: months of history, this week,
and a "today" that shows every state of the live board, whatever the hour or the day.
Everything comes from the random.Random it receives, so the same seed number at the
same moment gives the same transports. The seed_demo command saves the result.

Where a case depends on a business rule (how long a loading has run, this week's
average), the seed asks dockops instead of repeating the rule here.
"""
import random
from dataclasses import replace
from datetime import datetime, time, timedelta

from dockops import live, rules
from dockops.models import DISPATCHED_STATUSES, CargoType, OpsConfig, Status, Transport

DRY, COLD = CargoType.DRY, CargoType.COLD
ONE_DAY = timedelta(days=1)
HISTORY_DAYS = 90

CARRIERS = ("Northwind Haulage", "Bluefin Freight", "Kestrel Lines", "Arcturus Cargo",
            "Silverline Transport", "Cobalt Road Co.")
PLANNERS = ("A. Rowan", "J. Keller", "M. Soto", "L. Park")
DESTINATIONS = ("Port Aster", "Vale Junction", "Corin Bay", "Halden", "North Reach", "Elm Crossing")
NOTES = ("Mixed pallets, check labels", "Driver requested an early slot", "Seal replaced at the gate",
         "Waiting for paperwork", "Fragile load, no stacking")

# Planned times after the appointment: loading start, loading end, departure.
PLAN_OFFSETS = {DRY: (60, 180, 240), COLD: (60, 240, 300)}
# Typical actual loading time in minutes: cold loads take longer.
TYPICAL_LOADING = {DRY: 120, COLD: 190}
# Appointment slots of a past day, chosen so that loadings never cross the break.
SLOTS = (time(6, 30), time(7, 0), time(7, 30), time(13, 0), time(13, 30), time(14, 0), time(14, 30))
# Old transports nobody closed: the history page lists them.
UNCLOSED_DAYS_AGO = (12, 26, 41, 63)


def minutes(amount: float) -> timedelta:
    return timedelta(minutes=amount)


def seed_transports(now: datetime, rng: random.Random, config: OpsConfig) -> list[Transport]:
    """A whole demo operation around `now` (see Replica docs/DEMO-DATA.md)."""
    now = now.replace(second=0, microsecond=0)
    make = _Factory(rng, config.bays)

    history = _history(make, now, config)
    finished_today = _finished_today(make, now, config)
    references = _loading_references(history + finished_today, now, config)
    at_bay = _loadings_in_progress(make, now, config, references) + [t for t in finished_today if t.is_at_bay]
    at_bay, free_bays = _assign_bays(make, at_bay, config)
    incoming = _incoming(make, now, free_bays)

    left_today = [t for t in finished_today if not t.is_at_bay]
    return history + left_today + at_bay + incoming


# ------------------------------------------------------------------- The parts of the operation

def _history(make: "_Factory", now: datetime, config: OpsConfig) -> list[Transport]:
    """Completed visits on every past working day, plus a few transports nobody closed."""
    transports = []
    for days_ago in range(HISTORY_DAYS, 0, -1):
        day = now.date() - days_ago * ONE_DAY
        if days_ago in UNCLOSED_DAYS_AGO:
            transports.append(make.transport(datetime.combine(day, time(10)), make.cargo(), status=Status.SCHEDULED))
        if rules.is_rest_day(day, config):
            continue
        for slot in sorted(make.rng.sample(SLOTS, make.rng.randint(3, 5))):
            cargo = make.cargo()
            loading = make.loading_minutes(cargo)
            loading_end = datetime.combine(day, slot) + minutes(60 + loading) + make.random_minutes(-10, 20, 0)
            status = Status.DELIVERED if days_ago > 2 else Status.IN_TRANSIT
            visit = make.visit(loading_end, cargo, status, loading)
            if make.rng.random() < 0.04:        # a planner forgot part of the plan: "no plan"
                visit = replace(visit, planned_loading_start=None, planned_loading_end=None)
            transports.append(visit)
    return transports


def _finished_today(make: "_Factory", now: datetime, config: OpsConfig) -> list[Transport]:
    """
    Loadings that already ended today, and the carryovers.

    Three of them end today even at 00:05, so this week always has an average loading
    time per cargo type for the timers to compare with. Their start is worked out with
    the rules, so a loading that crosses the night still measures a typical time.
    """
    today = now.date()
    midnight = datetime.combine(today, time.min)

    def dispatched_today(minutes_ago: int, cargo: CargoType) -> Transport:
        loading_end = max(now - minutes(minutes_ago), midnight)
        started = _start_for(make.loading_minutes(cargo), loading_end, config, finished=True)
        departure = _whole_minute(loading_end + (now - loading_end) / 2)
        return make.visit(loading_end, cargo, Status.DISPATCHED, started=started, departed_at=departure)

    two_days_ago, yesterday = today - 2 * ONE_DAY, today - ONE_DAY
    still_at_bay = make.visit(datetime.combine(two_days_ago, time(18, 40)), DRY, Status.LOADED)
    left_today = make.visit(datetime.combine(yesterday, time(19, 30)), COLD, Status.DISPATCHED,
                            departed_at=max(now - minutes(60), midnight))
    return [
        dispatched_today(150, DRY),
        dispatched_today(100, DRY),
        dispatched_today(120, COLD),
        replace(still_at_bay, notes="Waiting for seal confirmation"),   # carryover, departure overdue
        left_today,                                                     # carryover dispatched today
    ]


def _loading_references(transports: list[Transport], now: datetime, config: OpsConfig) -> dict[CargoType, float]:
    """This week's average loading time per cargo type, exactly as the live board computes it."""
    chart = live.build_live_payload(transports, now, config)["loading_chart"]["by_cargo_type"]
    return {cargo: chart[cargo.value]["week_average"] or config.loading_limit_minutes for cargo in CargoType}


def _loadings_in_progress(make: "_Factory", now: datetime, config: OpsConfig,
                          references: dict[CargoType, float]) -> list[Transport]:
    """One loading per timer level, the cold-versus-dry case, and one not started yet."""
    dry_ref, cold_ref = references[DRY], references[COLD]
    targets = [
        (DRY, dry_ref * 0.5),                                       # ok
        (DRY, dry_ref + 10),                                        # warning
        (DRY, dry_ref + config.critical_excess_minutes + 15),       # critical
        (COLD, (dry_ref + cold_ref) / 2),                           # ok for cold, late if it were dry
    ]
    loading = [make.loading(_start_for(target, now, config, finished=False), cargo) for cargo, target in targets]
    return loading + [make.inspected(now - minutes(10), COLD)]


def _assign_bays(make: "_Factory", at_bay: list[Transport], config: OpsConfig) -> tuple[list[Transport], list[int]]:
    """Give each transport at a bay its own bay, always keeping two configured bays free."""
    at_bay = at_bay[:max(len(config.bays) - 2, 0)]
    bays = list(config.bays)
    make.rng.shuffle(bays)
    placed = [replace(transport, bay=bay) for transport, bay in zip(at_bay, bays)]
    free = sorted(bays[len(placed):])
    return placed, free


def _incoming(make: "_Factory", now: datetime, free_bays: list[int]) -> list[Transport]:
    """The yard, the overdue arrivals and the appointments of today, tomorrow and later."""
    today = now.date()
    tomorrow = today + ONE_DAY
    yesterday = today - ONE_DAY
    return [
        make.waiting(now - minutes(25), now - minutes(15), DRY, bay=free_bays[0] if free_bays else None),
        make.waiting(now - minutes(60), now - minutes(15), COLD),                        # arrived late
        make.transport(now - minutes(50), DRY, status=Status.SCHEDULED),                 # overdue arrival
        make.transport(datetime.combine(yesterday, time(10)), DRY, status=Status.SCHEDULED,
                       notes="Carrier not answering"),                                   # carryover, never arrived
        *[make.transport(moment, make.cargo(), status=Status.SCHEDULED) for moment in _later_today(now, 3)],
        *[make.transport(datetime.combine(tomorrow, slot), make.cargo(), status=Status.SCHEDULED)
          for slot in (time(7, 30), time(9), time(14))],
        make.transport(datetime.combine(today + 2 * ONE_DAY, time(8)), DRY, status=Status.SCHEDULED),  # not listed yet
    ]


# ------------------------------------------------------------------- Helpers

def _start_for(target_minutes: float, end: datetime, config: OpsConfig, *, finished: bool) -> datetime:
    """
    The latest loading start, in 5-minute steps, whose loading time reaches the target.

    finished  True: a loading that ended at `end`. False: a loading still running at `end` (now).
    The loading time comes from dockops, so breaks, nights and rest days are handled exactly
    as the board will measure them.
    """
    start = end
    for _ in range(7 * 24 * 12):            # a week back is far more than any target needs
        if finished:
            measured = rules.working_minutes(start, end, config, count_activity=True)
        else:
            measured = rules.loading_minutes_so_far(start, end, config)
        if measured >= target_minutes:
            break
        start -= minutes(5)
    return start


def _later_today(now: datetime, count: int) -> list[datetime]:
    """`count` moments spread between now and the end of today."""
    end_of_day = datetime.combine(now.date(), time(23, 59))
    gap = (end_of_day - now) / (count + 1)
    return [_whole_minute(now + gap * (i + 1)) for i in range(count)]


def _whole_minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


class _Factory:
    """Makes coherent transports with invented names and numbers, all from one random generator."""

    def __init__(self, rng: random.Random, bays: tuple[int, ...]):
        self.rng = rng
        self.bays = bays
        self.count = 0

    # --- random pieces

    def cargo(self) -> CargoType:
        return COLD if self.rng.random() < 1 / 3 else DRY

    def random_minutes(self, low: int, high: int, mode: int) -> timedelta:
        return minutes(round(self.rng.triangular(low, high, mode)))

    def loading_minutes(self, cargo: CargoType) -> int:
        typical = TYPICAL_LOADING[cargo]
        return round(min(max(self.rng.gauss(typical, typical * 0.12), typical * 0.75), typical * 1.25))

    def note(self) -> str:
        return self.rng.choice(NOTES) if self.rng.random() < 0.15 else ""

    # --- transports

    def transport(self, appointment: datetime, cargo: CargoType, **fields) -> Transport:
        """A transport planned from its appointment (DEMO-DATA planning pattern), plus `fields`."""
        self.count += 1
        start, end, departure = PLAN_OFFSETS[cargo]
        return Transport(**{
            "number": f"T-{20000 + self.count}",
            "cargo_type": cargo,
            "planned_arrival": appointment,
            "planned_loading_start": appointment + minutes(start),
            "planned_loading_end": appointment + minutes(end),
            "planned_departure": appointment + minutes(departure),
            "carrier": self.rng.choice(CARRIERS),
            "planner": self.rng.choice(PLANNERS),
            "destination": self.rng.choice(DESTINATIONS),
            "booking_ref": f"BK-{self.rng.randint(100000, 999999)}",
            **fields,
        })

    def visit(self, loading_end: datetime, cargo: CargoType, status: Status, loading: int | None = None,
              started: datetime | None = None, departed_at: datetime | None = None) -> Transport:
        """A visit whose loading ended at `loading_end`; the earlier times are worked out backwards."""
        started = started or loading_end - minutes(loading or self.loading_minutes(cargo))
        appointment = started - minutes(60) + self.random_minutes(-20, 10, 0)
        arrived = min(appointment + self.random_minutes(-15, 35, 0), started - minutes(20))
        inspected = min(arrived + self.random_minutes(5, 28, 12), started - minutes(5))
        if status in DISPATCHED_STATUSES and departed_at is None:
            departed_at = loading_end + self.random_minutes(15, 60, 25)
        return self.transport(
            appointment, cargo, status=status, bay=self.rng.choice(self.bays) if self.bays else None,
            arrived_at=arrived, inspected_at=inspected,
            loading_started_at=started, loading_ended_at=loading_end, departed_at=departed_at,
            seal_number=f"S-{self.rng.randint(10000, 99999)}", notes=self.note(),
        )

    def loading(self, started: datetime, cargo: CargoType) -> Transport:
        """A loading in progress since `started`."""
        appointment = started - minutes(60) + self.random_minutes(-10, 10, 0)
        arrived = appointment + self.random_minutes(-15, 15, 0)
        return self.transport(
            appointment, cargo, status=Status.LOADING, arrived_at=arrived,
            inspected_at=arrived + self.random_minutes(5, 18, 10), loading_started_at=started, notes=self.note(),
        )

    def inspected(self, inspected_at: datetime, cargo: CargoType) -> Transport:
        """At its bay, inspected, loading not started yet (planned to start soon)."""
        arrived = inspected_at - self.random_minutes(8, 15, 10)
        return self.transport(arrived + self.random_minutes(-10, 10, 0), cargo, status=Status.INSPECTED,
                              arrived_at=arrived, inspected_at=inspected_at)

    def waiting(self, appointment: datetime, arrived_at: datetime, cargo: CargoType, bay: int | None = None) -> Transport:
        """Arrived and waiting in the yard (a bay may already be assigned)."""
        return self.transport(appointment, cargo, status=Status.WAITING, arrived_at=arrived_at, bay=bay)
