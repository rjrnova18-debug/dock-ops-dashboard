"""
The business rules of the dock operation, as pure functions.

Every function receives its data and returns a result: no database, no clock, no
framework. "Now" is always a parameter, which is what makes the rules testable.

Three groups, in the order they build on each other (rule numbers refer to docs/RULES.md):
    1. Working time    how long something took, counting only time that was worked
    2. Checkpoints     did each moment of the visit happen on time?
    3. Indicator days  on which day, and in which period, does each thing count?
"""
from datetime import date, datetime, time, timedelta

from dockops.models import Checkpoint, OpsConfig, Outcome, Transport

ONE_DAY = timedelta(days=1)


# ----------------------------------------------------------------- 1. Working time

def working_minutes(start: datetime | None, end: datetime | None, config: OpsConfig, *,
                    count_activity: bool = False, end_is_now: bool = False) -> float | None:
    """
    Minutes of working time between start and end (rules W1-W5).

    Working time is the shift minus the break. A rest day in the middle of the range is
    skipped; it counts only when the range starts or ends on it.

    count_activity  apply the activity rule (used for loading): an idle period counts
                    when the range starts or ends inside it, because that proves someone
                    was working then.
    end_is_now      `end` is the current time of something still in progress, not a real
                    event, so it proves no activity. Only the start can.

    Returns None when a time is missing or the range is backwards.
    """
    if start is None or end is None or end < start:
        return None

    total = 0.0
    day = start.date()
    while day <= end.date():
        if not _is_skipped_rest_day(day, start, end, config):
            for period_start, period_end, is_working in _periods_of_day(day, config):
                counts = is_working or (
                    count_activity and _had_activity(period_start, period_end, start, end, end_is_now))
                if counts:
                    total += _overlap_minutes(start, end, period_start, period_end)
        day += ONE_DAY
    return total


def _periods_of_day(day: date, config: OpsConfig) -> list[tuple[datetime, datetime, bool]]:
    """The five consecutive periods of a day as (start, end, is_working)."""
    midnight = datetime.combine(day, time.min)
    shift_start = datetime.combine(day, config.shift_start)
    break_start = datetime.combine(day, config.break_start)
    break_end = datetime.combine(day, config.break_end)
    shift_end = datetime.combine(day, config.shift_end)
    return [
        (midnight, shift_start, False),           # before the shift
        (shift_start, break_start, True),
        (break_start, break_end, False),          # the break
        (break_end, shift_end, True),
        (shift_end, midnight + ONE_DAY, False),   # after the shift
    ]


def _is_skipped_rest_day(day: date, start: datetime, end: datetime, config: OpsConfig) -> bool:
    """A rest day counts only if the range starts or ends on it (someone did work that day)."""
    is_rest_day = config.rest_weekday is not None and day.weekday() == config.rest_weekday
    return is_rest_day and day not in (start.date(), end.date())


def _had_activity(period_start: datetime, period_end: datetime,
                  start: datetime, end: datetime, end_is_now: bool) -> bool:
    """Did the range start or end inside this period?"""
    started_inside = period_start <= start < period_end
    ended_inside = not end_is_now and period_start < end < period_end
    return started_inside or ended_inside


def _overlap_minutes(start: datetime, end: datetime, period_start: datetime, period_end: datetime) -> float:
    overlap_start = max(start, period_start)
    overlap_end = min(end, period_end)
    if overlap_end <= overlap_start:
        return 0.0
    return (overlap_end - overlap_start).total_seconds() / 60


def loading_minutes(transport: Transport, config: OpsConfig) -> float | None:
    """Loading time: from loading start to loading end, with the activity rule."""
    return working_minutes(transport.loading_started_at, transport.loading_ended_at, config,
                           count_activity=True)


def loading_minutes_so_far(started_at: datetime, now: datetime, config: OpsConfig) -> float:
    """Loading time of a loading still in progress, up to `now` (rule W5)."""
    minutes = working_minutes(started_at, now, config, count_activity=True, end_is_now=True)
    return minutes or 0.0      # a start time ahead of the clock counts as "just started"


def is_loading_clock_running(started_at: datetime, now: datetime, config: OpsConfig) -> bool:
    """
    Is the clock of a loading in progress advancing right now? (rule W5)

    It runs during working time. In an idle period it runs only if the loading started
    inside that same period; otherwise it is paused until work resumes.
    """
    for period_start, period_end, is_working in _periods_of_day(now.date(), config):
        if period_start <= now < period_end:
            return is_working or period_start <= started_at < period_end
    return False


def cycle_minutes(transport: Transport, config: OpsConfig) -> float | None:
    """Cycle time: from actual arrival to departure. The activity rule does not apply."""
    return working_minutes(transport.arrived_at, transport.departed_at, config)


# ----------------------------------------------------------------- 2. Checkpoints

def compare_with_expected(expected: datetime | None, actual: datetime | None,
                          tolerance_minutes: int, now: datetime | None = None) -> Outcome:
    """
    The outcome of one checkpoint (rules C1-C4).

    With `now`, a checkpoint that has not happened but is already past its tolerance is
    overdue and counts as LATE. Without `now`, it stays PENDING.
    """
    tolerance = timedelta(minutes=tolerance_minutes)

    if expected is None:
        return Outcome.PENDING if actual is None else Outcome.NO_PLAN

    if actual is None:
        is_overdue = now is not None and now - expected > tolerance
        return Outcome.LATE if is_overdue else Outcome.PENDING

    return Outcome.ON_TIME if actual - expected <= tolerance else Outcome.LATE


def checkpoint_times(transport: Transport, checkpoint: Checkpoint) -> tuple[datetime | None, datetime | None]:
    """
    (expected, actual) of a checkpoint.

    Inspection has no planned time: it is expected from the actual arrival (rule C5).
    """
    t = transport
    times = {
        Checkpoint.ARRIVAL: (t.planned_arrival, t.arrived_at),
        Checkpoint.INSPECTION: (t.arrived_at, t.inspected_at),
        Checkpoint.LOADING_START: (t.planned_loading_start, t.loading_started_at),
        Checkpoint.LOADING_END: (t.planned_loading_end, t.loading_ended_at),
        Checkpoint.DEPARTURE: (t.planned_departure, t.departed_at),
    }
    return times[checkpoint]


def checkpoint_tolerance(checkpoint: Checkpoint, config: OpsConfig) -> int:
    """Minutes of delay a checkpoint allows. Inspection uses its own limit (rule C5)."""
    if checkpoint is Checkpoint.INSPECTION:
        return config.inspection_limit_minutes
    return config.tolerance_minutes


def checkpoint_outcome(transport: Transport, checkpoint: Checkpoint, config: OpsConfig,
                       now: datetime | None = None) -> Outcome:
    """Outcome of one checkpoint of a transport."""
    expected, actual = checkpoint_times(transport, checkpoint)
    return compare_with_expected(expected, actual, checkpoint_tolerance(checkpoint, config), now)


def adherence_percent(outcomes: list[Outcome]) -> int | None:
    """
    Adherence: percentage of ON_TIME among the outcomes that are ON_TIME or LATE (rule C6).

    PENDING and NO_PLAN are ignored. Returns None, not 0, when nothing can be judged
    yet: "no data so far" and "everything was late" must not look the same.
    """
    judged = [outcome for outcome in outcomes if outcome in (Outcome.ON_TIME, Outcome.LATE)]
    if not judged:
        return None
    on_time = sum(1 for outcome in judged if outcome is Outcome.ON_TIME)
    return int(round(on_time / len(judged) * 100))


# ----------------------------------------------------------------- 3. Indicator days

def dispatch_day(transport: Transport) -> date | None:
    """Day a dispatched transport left. Without a departure time, its appointment day (rule D1)."""
    if not transport.is_dispatched:
        return None
    if transport.departed_at:
        return transport.departed_at.date()
    return transport.appointment_day


def loading_day(transport: Transport) -> date | None:
    """Day the loading ended. Only a loading with both start and end counts (rule D2)."""
    if transport.loading_started_at is None or transport.loading_ended_at is None:
        return None
    return transport.loading_ended_at.date()


def cycle_day(transport: Transport) -> date | None:
    """Day the cycle closed: the departure day. Needs an actual arrival too (rule D3)."""
    if transport.arrived_at is None or transport.departed_at is None:
        return None
    return transport.departed_at.date()


def checkpoint_day(transport: Transport, checkpoint: Checkpoint) -> date | None:
    """Day a checkpoint was expected. Without an expected time, the day it happened (rule D4)."""
    expected, actual = checkpoint_times(transport, checkpoint)
    moment = expected or actual
    return moment.date() if moment else None


def in_workload(transport: Transport, period_start: date, period_end: date, config: OpsConfig) -> bool:
    """
    Is the transport part of what the period [period_start, period_end] had to dispatch? (rule D5)

    Yes when any of these is true:
      - its appointment is in the period
      - it was dispatched in the period
      - it is a carryover: its appointment was up to `carryover_days` before the period
        and it had not been dispatched when the period started
    """
    appointment = transport.appointment_day
    dispatched_on = dispatch_day(transport)

    if appointment is not None and period_start <= appointment <= period_end:
        return True
    if dispatched_on is not None and period_start <= dispatched_on <= period_end:
        return True
    if appointment is None:
        return False

    oldest_carryover = period_start - timedelta(days=config.carryover_days)
    appointment_just_before = oldest_carryover <= appointment < period_start
    left_before_period = dispatched_on is not None and dispatched_on < period_start
    return appointment_just_before and not left_before_period


def week_of(day: date, config: OpsConfig) -> tuple[date, date]:
    """(first day, last day) of the reporting week that contains `day` (rule D6)."""
    days_into_week = (day.weekday() - config.week_start_weekday) % 7
    first_day = day - timedelta(days=days_into_week)
    return first_day, first_day + timedelta(days=6)
