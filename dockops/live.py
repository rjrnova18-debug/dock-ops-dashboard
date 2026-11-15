"""
The live board: everything the main screen shows, built from a list of transports.

One public function, build_live_payload(), returns a plain dict ready to be sent as
JSON. Below it there is one function per section of the screen, in the order the
sections appear in the payload. All the business rules come from rules.py; this module
only decides which transports each section looks at and how its data is laid out.

The scope of each section (rules L1-L9) is described in docs/LIVE-BOARD.md and the
exact shape of the payload in docs/API-CONTRACT.md.
"""
from collections import Counter
from datetime import date, datetime, timedelta
from typing import NamedTuple

from dockops import rules
from dockops.models import CargoType, Checkpoint, OpsConfig, Outcome, Status, Transport

# The week's indicators need transports whose appointment is older than the week
# (carryovers dispatched in it). Callers may limit what they load to appointments
# from this many days back; older transports cannot change the board.
LOOKBACK_DAYS = 35

Period = tuple[date, date]      # (first day, last day), both included


def build_live_payload(transports: list[Transport], now: datetime, config: OpsConfig,
                       data_updated_at: datetime | None = None) -> dict:
    """
    The whole live board as a JSON-ready dict.

    transports       every transport that may matter (see LOOKBACK_DAYS)
    now              the server's current time; the screen's clocks are based on it
    data_updated_at  when the transports' data last changed, to warn if it is out of date
    """
    today = now.date()
    week = rules.week_of(today, config)
    board = [t for t in transports if _in_board_window(t, today, config)]
    active = [t for t in board if _is_active_today(t, today)]

    loadings = _loading_measures(transports, week, config)
    cycles = _cycle_measures(transports, week, config)
    trend_days = sorted({m.day for m in loadings} | {m.day for m in cycles})
    references = _loading_references(loadings)

    return {
        "generated_at": _iso(now),
        "data_updated_at": _iso(data_updated_at),
        "data_is_stale": _is_stale(data_updated_at, now, config),
        "week": _week_section(transports, week, now, config),
        "status_chart": _status_chart(active, config),
        "loading_chart": _trend_chart(loadings, trend_days),
        "cycle_chart": _trend_chart(cycles, trend_days),
        "adherence_chart": _adherence_chart(active, now, config),
        "bays": _bays_section(board, now, config, references),
        "incoming": _incoming_section(board, now, config),
    }


# ----------------------------------------------------------------- Which transports

def _in_board_window(transport: Transport, today: date, config: OpsConfig) -> bool:
    """
    Rule L1: the board looks at appointments from `carryover_days` ago onwards.

    An older transport that nobody closed must not stay on the screen forever.
    A transport without an appointment is kept, so it is not silently lost.
    """
    appointment = transport.appointment_day
    if appointment is None:
        return True
    return appointment >= today - timedelta(days=config.carryover_days)


def _is_active_today(transport: Transport, today: date) -> bool:
    """
    Rule L2: the active operation is today's appointments plus the carryovers.

    A carryover dispatched today still counts today, so it does not vanish from the
    charts at the very moment it is solved.
    """
    appointment = transport.appointment_day
    if appointment is None or appointment > today:
        return False
    if appointment == today:
        return True
    departed_today = transport.departed_at is not None and transport.departed_at.date() == today
    return not transport.is_dispatched or departed_today


def _is_stale(data_updated_at: datetime | None, now: datetime, config: OpsConfig) -> bool:
    if data_updated_at is None:
        return True
    return now - data_updated_at > timedelta(minutes=config.stale_after_minutes)


# ----------------------------------------------------------------- Week counter (rule L3)

def _week_section(transports: list[Transport], week: Period, now: datetime, config: OpsConfig) -> dict:
    """How much of the week's workload has been dispatched, and which transports those are."""
    week_start, week_end = week
    dispatched = [t for t in transports if _in_period(rules.dispatch_day(t), week)]
    workload = [t for t in transports if rules.in_workload(t, week_start, week_end, config)]
    return {
        "start": week_start.isoformat(),
        "end": week_end.isoformat(),
        "dispatched": len(dispatched),
        "workload": len(workload),
        "completed": [_completed_row(t, now, config) for t in _sorted_by_bay(dispatched, config)],
    }


def _completed_row(transport: Transport, now: datetime, config: OpsConfig) -> dict:
    t = transport
    return {
        "number": t.number,
        "bay": t.bay,
        "status": t.status.value,
        "cargo_type": t.cargo_type.value,
        "arrived_at": _iso(t.arrived_at),
        "departed_at": _iso(t.departed_at),
        "loading": _duration(t.loading_started_at, t.loading_ended_at, rules.loading_minutes(t, config)),
        "cycle": _duration(t.arrived_at, t.departed_at, rules.cycle_minutes(t, config)),
        "carrier": t.carrier,
        "notes": t.notes,
        "detail": transport_detail(t, now, config),
    }


# ----------------------------------------------------------------- Status chart (rule L4)

def _status_chart(active: list[Transport], config: OpsConfig) -> dict:
    """How many transports of the active operation are in each status."""
    counts = Counter(t.status for t in active)
    return {
        "counts": [{"status": status.value, "count": counts[status]} for status in Status if counts[status]],
        "rows": [
            {
                "number": t.number,
                "bay": t.bay,
                "status": t.status.value,
                "appointment_day": _iso_day(t.appointment_day),
                "carrier": t.carrier,
                "booking_ref": t.booking_ref,
            }
            for t in _sorted_by_bay(active, config)
        ],
    }


# ----------------------------------------------------------------- Trend charts (rule L5)

class Measure(NamedTuple):
    """One measured duration (a loading or a cycle) and the day it counts on."""
    day: date
    transport: Transport
    start: datetime
    end: datetime
    minutes: float


def _loading_measures(transports: list[Transport], week: Period, config: OpsConfig) -> list[Measure]:
    """The loadings that ended this week."""
    measures = []
    for t in transports:
        minutes = rules.loading_minutes(t, config)
        if minutes is not None and _in_period(rules.loading_day(t), week):
            measures.append(Measure(rules.loading_day(t), t, t.loading_started_at, t.loading_ended_at, minutes))
    return measures


def _cycle_measures(transports: list[Transport], week: Period, config: OpsConfig) -> list[Measure]:
    """The cycles that closed (departed) this week."""
    measures = []
    for t in transports:
        minutes = rules.cycle_minutes(t, config)
        if minutes is not None and _in_period(rules.cycle_day(t), week):
            measures.append(Measure(rules.cycle_day(t), t, t.arrived_at, t.departed_at, minutes))
    return measures


def _trend_chart(measures: list[Measure], days: list[date]) -> dict:
    """
    Average duration per day, in total and per cargo type.

    `days` is shared by the loading and the cycle chart: the days of the week that
    already have a measure in either. A day without measures in this chart is None.
    """
    by_cargo_type = {}
    for cargo_type in CargoType:
        of_type = [m for m in measures if m.transport.cargo_type is cargo_type]
        by_cargo_type[cargo_type.value] = {
            "daily_average": _daily_averages(of_type, days),
            "week_average": _average([m.minutes for m in of_type]),
            "count": len(of_type),
        }
    return {
        "days": [day.isoformat() for day in days],
        "daily_average": _daily_averages(measures, days),
        "week_average": _average([m.minutes for m in measures]),
        "by_cargo_type": by_cargo_type,
        "rows": [_measure_row(m) for m in sorted(measures, key=lambda m: (m.day, m.start))],
    }


def _daily_averages(measures: list[Measure], days: list[date]) -> list[float | None]:
    return [_average([m.minutes for m in measures if m.day == day]) for day in days]


def _measure_row(measure: Measure) -> dict:
    t = measure.transport
    return {
        "day": measure.day.isoformat(),
        "number": t.number,
        "bay": t.bay,
        "cargo_type": t.cargo_type.value,
        "start": _iso(measure.start),
        "end": _iso(measure.end),
        **_duration(measure.start, measure.end, measure.minutes),
    }


def _loading_references(loadings: list[Measure]) -> dict[CargoType, float]:
    """Rule L8: this week's average loading time of each cargo type that has one."""
    references = {}
    for cargo_type in CargoType:
        average = _average([m.minutes for m in loadings if m.transport.cargo_type is cargo_type])
        if average:
            references[cargo_type] = average
    return references


# ----------------------------------------------------------------- Adherence chart (rule L6)

def _adherence_chart(active: list[Transport], now: datetime, config: OpsConfig) -> dict:
    """Adherence of each checkpoint over the active operation, in total and per cargo type."""
    by_cargo_type = {}
    for cargo_type in CargoType:
        of_type = [t for t in active if t.cargo_type is cargo_type]
        by_cargo_type[cargo_type.value] = {
            "percent": _adherence_percents(of_type, now, config),
            "count": len(of_type),
        }
    return {
        "checkpoints": [checkpoint.value for checkpoint in Checkpoint],
        "percent": _adherence_percents(active, now, config),
        "by_cargo_type": by_cargo_type,
        "rows": [
            {
                "number": t.number,
                "bay": t.bay,
                "cargo_type": t.cargo_type.value,
                "appointment_day": _iso_day(t.appointment_day),
                "checkpoints": _checkpoint_rows(t, now, config),
            }
            for t in _sorted_by_bay(active, config)
        ],
    }


def _adherence_percents(transports: list[Transport], now: datetime, config: OpsConfig) -> list[int | None]:
    """One percentage per checkpoint, in Checkpoint order. None = nothing to judge yet."""
    percents = []
    for checkpoint in Checkpoint:
        outcomes = [rules.checkpoint_outcome(t, checkpoint, config, now) for t in transports]
        percents.append(rules.adherence_percent(outcomes))
    return percents


# ----------------------------------------------------------------- Bays (rules L7, L8)

def _bays_section(board: list[Transport], now: datetime, config: OpsConfig,
                  references: dict[CargoType, float]) -> list[dict]:
    """
    One entry per configured bay, with the transports at it (empty list = free bay).

    A transport at a bay that is not configured (or with no bay number) gets an extra
    entry at the end, so it is never lost.
    """
    at_bay = [t for t in board if t.is_at_bay]

    def rows_for(transports):
        return [_bay_row(t, now, config, references) for t in transports]

    bays = [
        {"bay": number, "is_configured": True, "transports": rows_for(t for t in at_bay if t.bay == number)}
        for number in config.bays
    ]
    elsewhere = [t for t in at_bay if t.bay not in config.bays]
    for transport in _sorted_by_bay(elsewhere, config):
        bays.append({"bay": transport.bay, "is_configured": False, "transports": rows_for([transport])})
    return bays


def _bay_row(transport: Transport, now: datetime, config: OpsConfig,
             references: dict[CargoType, float]) -> dict:
    row = _board_row(transport, now, config)
    row["timer"] = _loading_timer(transport, now, config, references)
    over_reference = row["timer"]["over_reference_minutes"]
    if over_reference is not None and over_reference >= config.alert_excess_minutes:
        row["alerts"].append("loading_over_reference")
    return row


def _loading_timer(transport: Transport, now: datetime, config: OpsConfig,
                   references: dict[CargoType, float]) -> dict:
    """
    The loading clock of a transport at a bay (rule L8).

    The server does all the working-time maths. The screen only adds the seconds that
    pass between two refreshes while the state is "running".
    """
    timer = {
        "state": "not_started",        # not_started | running | paused | finished | missing_times
        "elapsed_seconds": None,
        "reference_minutes": None,
        "reference_kind": None,        # "average" of its cargo type, or the fixed "limit"
        "over_reference_minutes": None,
        "level": None,                 # ok | warning | critical
        "paused_by": None,             # break | off_shift
    }
    started_at = transport.loading_started_at

    if transport.status is Status.LOADED:
        minutes = rules.loading_minutes(transport, config)
        if minutes is None:
            timer["state"] = "missing_times"
        else:
            timer["state"] = "finished"
            timer["elapsed_seconds"] = int(minutes * 60)
        return timer

    if transport.status is not Status.LOADING:
        return timer                   # inspected: at the bay, loading not started
    if started_at is None:
        timer["state"] = "missing_times"
        return timer

    reference = references.get(transport.cargo_type)
    timer["reference_kind"] = "average" if reference else "limit"
    reference = reference or config.loading_limit_minutes
    minutes = rules.loading_minutes_so_far(started_at, now, config)
    over_reference = minutes - reference

    timer["elapsed_seconds"] = int(minutes * 60)
    timer["reference_minutes"] = reference
    timer["over_reference_minutes"] = round(over_reference, 1)
    if over_reference >= config.critical_excess_minutes:
        timer["level"] = "critical"
    elif over_reference >= 0:
        timer["level"] = "warning"
    else:
        timer["level"] = "ok"

    if rules.is_loading_clock_running(started_at, now, config):
        timer["state"] = "running"
    else:
        timer["state"] = "paused"
        in_break = config.break_start <= now.time() < config.break_end
        timer["paused_by"] = "break" if in_break else "off_shift"
    return timer


# ----------------------------------------------------------------- Incoming (rule L9)

def _incoming_section(board: list[Transport], now: datetime, config: OpsConfig) -> list[dict]:
    """
    Transports that are not at a bay yet: waiting in the yard or still to arrive.

    Late arrivals first (oldest appointment first), then the rest by appointment.
    """
    rows = []
    for transport in board:
        if transport.is_dispatched or transport.is_at_bay:
            continue
        group = _incoming_group(transport, now.date())
        if group is None:
            continue
        row = _board_row(transport, now, config)
        row["group"] = group
        row["is_late"] = row["arrival_outcome"] == Outcome.LATE.value
        rows.append(row)
    return sorted(rows, key=lambda row: (not row["is_late"], row["appointment"] or "9999"))


def _incoming_group(transport: Transport, today: date) -> str | None:
    """waiting | earlier | today | tomorrow, or None when it is too far ahead to show."""
    if transport.status is not Status.SCHEDULED:
        return "waiting"               # already here, in the yard

    # Without an appointment, the planned departure decides; without both, show it today.
    day = transport.appointment_day
    if day is None and transport.planned_departure:
        day = transport.planned_departure.date()

    if day is None or day == today:
        return "today"
    if day < today:
        return "earlier"
    if day == today + timedelta(days=1):
        return "tomorrow"
    return None


# ----------------------------------------------------------------- Shared by bays and incoming

def _board_row(transport: Transport, now: datetime, config: OpsConfig) -> dict:
    """What the operation table shows for one transport, plus its detail."""
    t = transport
    loading_start = rules.checkpoint_outcome(t, Checkpoint.LOADING_START, config, now)
    departure_overdue = t.planned_departure is not None and now > t.planned_departure

    alerts = []
    if loading_start is Outcome.LATE:
        alerts.append("late_loading_start")
    if _departure_is_near(t, now, config):
        alerts.append("departure_due")

    return {
        "number": t.number,
        "status": t.status.value,
        "cargo_type": t.cargo_type.value,
        "bay": t.bay,
        "is_carryover": t.appointment_day is not None and t.appointment_day < now.date(),
        "appointment": _iso(t.planned_arrival),
        "planned_loading_start": _iso(t.planned_loading_start),
        "planned_departure": _iso(t.planned_departure),
        "arrival_outcome": rules.checkpoint_outcome(t, Checkpoint.ARRIVAL, config, now).value,
        "loading_start_outcome": loading_start.value,
        "departure_overdue": departure_overdue,
        "alerts": alerts,
        "notes": t.notes,
        "detail": transport_detail(t, now, config),
    }


def _departure_is_near(transport: Transport, now: datetime, config: OpsConfig) -> bool:
    """The planned departure is within the warning time, or already passed."""
    if transport.planned_departure is None:
        return False
    return now >= transport.planned_departure - timedelta(minutes=config.departure_warning_minutes)


def transport_detail(transport: Transport, now: datetime, config: OpsConfig) -> dict:
    """Plan versus actual of every checkpoint, and the transport's descriptive data."""
    t = transport
    return {
        "checkpoints": _checkpoint_rows(t, now, config),
        "carrier": t.carrier,
        "planner": t.planner,
        "destination": t.destination,
        "booking_ref": t.booking_ref,
        "seal_number": t.seal_number,
    }


def _checkpoint_rows(transport: Transport, now: datetime, config: OpsConfig) -> list[dict]:
    rows = []
    for checkpoint in Checkpoint:
        expected, actual = rules.checkpoint_times(transport, checkpoint)
        tolerance = timedelta(minutes=rules.checkpoint_tolerance(checkpoint, config))
        rows.append({
            "checkpoint": checkpoint.value,
            "expected": _iso(expected),
            "deadline": _iso(expected + tolerance) if expected else None,
            "actual": _iso(actual),
            "outcome": rules.checkpoint_outcome(transport, checkpoint, config, now).value,
        })
    return rows


# ----------------------------------------------------------------- Small helpers

def _in_period(day: date | None, period: Period) -> bool:
    return day is not None and period[0] <= day <= period[1]


def _average(values: list[float]) -> float | None:
    """Average rounded to one decimal, or None when there is nothing to average."""
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _duration(start: datetime | None, end: datetime | None, working_minutes: float | None) -> dict | None:
    """Working time next to clock time, so a reader can see where the difference comes from."""
    if working_minutes is None:
        return None
    return {
        "working_minutes": round(working_minutes, 1),
        "clock_minutes": round((end - start).total_seconds() / 60, 1),
    }


def _sorted_by_bay(transports: list[Transport], config: OpsConfig) -> list[Transport]:
    """Configured bays in their display order, then other bays, then transports without bay."""
    def order(transport: Transport):
        if transport.bay in config.bays:
            return (0, config.bays.index(transport.bay))
        if transport.bay is not None:
            return (1, transport.bay)
        return (2, 0)
    return sorted(transports, key=order)


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat(timespec="seconds") if moment else None


def _iso_day(day: date | None) -> str | None:
    return day.isoformat() if day else None
