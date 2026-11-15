"""
The history page: indicators of any past period, built from a list of transports.

Two public functions:
    build_history_summary()   everything the page shows, as a JSON-ready dict
    fact_rows()               one row per transport, for the CSV and Excel downloads

It uses the same rules as the live board (rules.py), so both screens always agree:
every indicator counts on the day it happened, not on the day of the appointment.

What each part means is described in docs/HISTORY.md (rules H1-H9).
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from dockops import rules
from dockops.live import transport_detail
from dockops.models import CargoType, Checkpoint, OpsConfig, Outcome, Transport

GROUPINGS = ("day", "week", "month")
TOP_LOADINGS = 10        # how many slowest / fastest loadings are listed
MAX_UNCLOSED_ROWS = 200

# Indicators need transports whose appointment is older than the period (carryovers
# dispatched in it). Callers may limit what they load to appointments from this many
# days before the period; see docs/HISTORY.md for the full loading rule.
LOOKBACK_DAYS = 35

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# Columns of fact_rows(), in order. Other tools read the downloads by these names:
# never rename or reorder them; add new columns at the end.
FACT_COLUMNS = (
    "number", "appointment_day", "year", "month", "week_start", "weekday",
    "cargo_type", "status", "is_dispatched", "bay",
    "carrier", "booking_ref", "planner", "destination", "notes",
    "planned_arrival", "arrived_at", "inspected_at",
    "planned_loading_start", "loading_started_at",
    "planned_loading_end", "loading_ended_at",
    "planned_departure", "departed_at",
    "loading_minutes", "cycle_minutes",
    "arrival_outcome", "inspection_outcome", "loading_start_outcome",
    "loading_end_outcome", "departure_outcome",
    "dispatch_day", "loading_day", "cycle_day",
    "arrival_day", "inspection_day", "loading_start_day", "loading_end_day", "departure_day",
)


def build_history_summary(transports: list[Transport], period_start: date, period_end: date,
                          now: datetime, config: OpsConfig, group_by: str = "week",
                          cargo_type: CargoType | None = None) -> dict:
    """
    Everything the history page shows for [period_start, period_end], as a JSON-ready dict.

    transports   every transport that may matter for the period (see LOOKBACK_DAYS)
    group_by     how the series is split: "day", "week" or "month"
    cargo_type   only count transports of this cargo type; None = all
    """
    if group_by not in GROUPINGS:
        raise ValueError(f"group_by must be one of {GROUPINGS}")
    period = (period_start, period_end)

    if cargo_type is not None:
        transports = [t for t in transports if t.cargo_type is cargo_type]
    counted = [t for t in transports if _touches(t, period, config)]

    def key_of(day: date) -> str:
        return _bucket_key(day, group_by, config)

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "group_by": group_by,
        "cargo_type": cargo_type.value if cargo_type else None,
        "generated_at": now.isoformat(timespec="seconds"),
        "totals": _totals(counted, period, now, config),
        "by_cargo_type": {
            cargo.value: _totals(_of_type(counted, cargo), period, now, config) for cargo in CargoType
        },
        "series": _series(counted, period, now, config, key_of),
        "checkpoints": _checkpoint_breakdown(counted, period, now, config),
        "activity": _activity(transports, period),
        "slowest_loadings": _extreme_loadings(counted, period, now, config, slowest=True),
        "fastest_loadings": _extreme_loadings(counted, period, now, config, slowest=False),
        "unclosed": _unclosed(counted, period, now, config),
    }


def fact_rows(transports: list[Transport], period_start: date, period_end: date,
              now: datetime, config: OpsConfig, cargo_type: CargoType | None = None) -> list[dict]:
    """
    One row per transport counted in the period, with the columns of FACT_COLUMNS.

    Values are plain Python (text, numbers, booleans, dates, date-times, None): whoever
    writes the CSV or the Excel file decides how to format them.
    """
    period = (period_start, period_end)
    if cargo_type is not None:
        transports = [t for t in transports if t.cargo_type is cargo_type]
    return [_fact_row(t, now, config) for t in transports if _touches(t, period, config)]


# ----------------------------------------------------------------- Which transports (rule H1)

def _touches(transport: Transport, period: tuple[date, date], config: OpsConfig) -> bool:
    """
    A transport is counted in a period when it is part of its workload or any of its
    indicator days falls in it.
    """
    if rules.in_workload(transport, *period, config):
        return True
    return any(_in_period(day, period) for day in _indicator_days(transport))


def _indicator_days(transport: Transport) -> list[date]:
    """Every day on which this transport counts for something."""
    days = [transport.appointment_day, rules.dispatch_day(transport),
            rules.loading_day(transport), rules.cycle_day(transport)]
    days += [rules.checkpoint_day(transport, checkpoint) for checkpoint in Checkpoint]
    return [day for day in days if day is not None]


def _of_type(transports: list[Transport], cargo_type: CargoType) -> list[Transport]:
    return [t for t in transports if t.cargo_type is cargo_type]


# ----------------------------------------------------------------- Indicators (rules H2, H3)

@dataclass
class _Tally:
    """Running counts of one bucket (the whole period, or one day / week / month of it)."""
    appointments: int = 0
    dispatched: int = 0
    loading_minutes: list[float] = field(default_factory=list)
    cycle_minutes: list[float] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)

    def as_indicators(self) -> dict:
        return {
            "appointments": self.appointments,
            "dispatched": self.dispatched,
            "loading_average_minutes": _average(self.loading_minutes),
            "loading_count": len(self.loading_minutes),
            "cycle_average_minutes": _average(self.cycle_minutes),
            "cycle_count": len(self.cycle_minutes),
            "adherence_percent": rules.adherence_percent(self.outcomes),
        }


def _tally(transports: list[Transport], period: tuple[date, date], now: datetime,
           config: OpsConfig, key_of) -> dict[str, _Tally]:
    """
    Walk every transport once and add each thing it counts for to the bucket of its day.

    `key_of(day)` names the bucket a day belongs to. Things whose day is outside the
    period are not counted. A bucket exists as soon as anything falls in it.
    """
    tallies: dict[str, _Tally] = defaultdict(_Tally)

    def bucket_of(day: date | None) -> _Tally | None:
        """The tally of the bucket `day` belongs to, or None if the day does not count."""
        if not _in_period(day, period):
            return None
        return tallies[key_of(day)]

    for t in transports:
        bucket = bucket_of(t.appointment_day)
        if bucket is not None:
            bucket.appointments += 1

        bucket = bucket_of(rules.dispatch_day(t))
        if bucket is not None:
            bucket.dispatched += 1

        bucket = bucket_of(rules.loading_day(t))
        minutes = rules.loading_minutes(t, config)
        if bucket is not None and minutes is not None:
            bucket.loading_minutes.append(minutes)

        bucket = bucket_of(rules.cycle_day(t))
        minutes = rules.cycle_minutes(t, config)
        if bucket is not None and minutes is not None:
            bucket.cycle_minutes.append(minutes)

        for checkpoint in Checkpoint:
            bucket = bucket_of(rules.checkpoint_day(t, checkpoint))
            if bucket is not None:
                bucket.outcomes.append(rules.checkpoint_outcome(t, checkpoint, config, now))
    return tallies


def _totals(transports: list[Transport], period: tuple[date, date], now: datetime, config: OpsConfig) -> dict:
    """Indicators of the whole period, plus its workload."""
    tallies = _tally(transports, period, now, config, key_of=lambda day: "all")
    indicators = tallies.get("all", _Tally()).as_indicators()
    indicators["workload"] = sum(1 for t in transports if rules.in_workload(t, *period, config))
    return indicators


def _series(transports: list[Transport], period: tuple[date, date], now: datetime,
            config: OpsConfig, key_of) -> list[dict]:
    """Indicators of each day / week / month that has something to count, oldest first."""
    total = _tally(transports, period, now, config, key_of)
    by_type = {cargo: _tally(_of_type(transports, cargo), period, now, config, key_of) for cargo in CargoType}
    series = []
    for key in sorted(total):
        series.append({
            "key": key,
            **total[key].as_indicators(),
            "by_cargo_type": {
                cargo.value: by_type[cargo].get(key, _Tally()).as_indicators() for cargo in CargoType
            },
        })
    return series


def _bucket_key(day: date, group_by: str, config: OpsConfig) -> str:
    """The day itself, the first day of its week, or its month as 'YYYY-MM'."""
    if group_by == "day":
        return day.isoformat()
    if group_by == "week":
        return rules.week_of(day, config)[0].isoformat()
    return day.strftime("%Y-%m")


# ----------------------------------------------------------------- Checkpoints (rule H4)

def _checkpoint_breakdown(transports: list[Transport], period: tuple[date, date],
                          now: datetime, config: OpsConfig) -> list[dict]:
    """For each checkpoint expected in the period: adherence and how many of each outcome."""
    breakdown = []
    for checkpoint in Checkpoint:
        expected_in_period = [t for t in transports
                              if _in_period(rules.checkpoint_day(t, checkpoint), period)]

        def outcomes(group):
            return [rules.checkpoint_outcome(t, checkpoint, config, now) for t in group]

        counts = Counter(outcomes(expected_in_period))
        breakdown.append({
            "checkpoint": checkpoint.value,
            "percent": rules.adherence_percent(outcomes(expected_in_period)),
            "on_time": counts[Outcome.ON_TIME],
            "late": counts[Outcome.LATE],
            "no_plan": counts[Outcome.NO_PLAN],
            "pending": counts[Outcome.PENDING],
            "by_cargo_type": {
                cargo.value: rules.adherence_percent(outcomes(_of_type(expected_in_period, cargo)))
                for cargo in CargoType
            },
        })
    return breakdown


# ----------------------------------------------------------------- Activity calendar (rule H5)

def _activity(transports: list[Transport], period: tuple[date, date]) -> list[dict]:
    """
    One entry per day of the period: how many transports actually arrived and departed.

    It counts by the real date, not by the appointment: a transport expected on the 31st
    that arrived on the 1st counts on the 1st.
    """
    arrivals = Counter(t.arrived_at.date() for t in transports if t.arrived_at)
    departures = Counter(t.departed_at.date() for t in transports if t.departed_at)
    start, end = period
    days = []
    day = start
    while day <= end:
        days.append({"day": day.isoformat(), "arrivals": arrivals[day], "departures": departures[day]})
        day += timedelta(days=1)
    return days


# ----------------------------------------------------------------- Loadings and unclosed (rules H6, H7)

def _extreme_loadings(transports: list[Transport], period: tuple[date, date], now: datetime,
                      config: OpsConfig, slowest: bool) -> list[dict]:
    """The slowest (or fastest) loadings among those that ended in the period."""
    measured = []
    for t in transports:
        minutes = rules.loading_minutes(t, config)
        if minutes is not None and _in_period(rules.loading_day(t), period):
            measured.append((minutes, t))
    measured.sort(key=lambda pair: pair[0], reverse=slowest)      # stable: ties keep their order

    rows = []
    for minutes, t in measured[:TOP_LOADINGS]:
        cycle = rules.cycle_minutes(t, config)
        rows.append({
            "number": t.number,
            "cargo_type": t.cargo_type.value,
            "appointment_day": _iso(t.appointment_day),
            "bay": t.bay,
            "carrier": t.carrier,
            "loading_started_at": _iso(t.loading_started_at),
            "loading_ended_at": _iso(t.loading_ended_at),
            "loading_minutes": round(minutes, 1),
            "cycle_minutes": round(cycle, 1) if cycle is not None else None,
            "detail": transport_detail(t, now, config),
        })
    return rows


def _unclosed(transports: list[Transport], period: tuple[date, date], now: datetime, config: OpsConfig) -> dict:
    """
    Transports with an appointment in the period that were never dispatched and are too
    old for the live board to show. Almost always records nobody closed.
    """
    oldest_on_board = now.date() - timedelta(days=config.carryover_days)
    forgotten = [t for t in transports
                 if not t.is_dispatched
                 and _in_period(t.appointment_day, period)
                 and t.appointment_day < oldest_on_board]
    forgotten.sort(key=lambda t: t.appointment_day)
    return {
        "total": len(forgotten),
        "rows": [
            {
                "number": t.number,
                "appointment_day": _iso(t.appointment_day),
                "status": t.status.value,
                "cargo_type": t.cargo_type.value,
                "carrier": t.carrier,
                "notes": t.notes,
            }
            for t in forgotten[:MAX_UNCLOSED_ROWS]
        ],
    }


# ----------------------------------------------------------------- Fact table (rule H8)

def _fact_row(transport: Transport, now: datetime, config: OpsConfig) -> dict:
    t = transport
    day = t.appointment_day
    loading = rules.loading_minutes(t, config)
    cycle = rules.cycle_minutes(t, config)
    row = {
        "number": t.number,
        "appointment_day": day,
        "year": day.year if day else None,
        "month": day.month if day else None,
        "week_start": rules.week_of(day, config)[0] if day else None,
        "weekday": WEEKDAYS[day.weekday()] if day else "",
        "cargo_type": t.cargo_type.value,
        "status": t.status.value,
        "is_dispatched": t.is_dispatched,
        "bay": t.bay,
        "carrier": t.carrier,
        "booking_ref": t.booking_ref,
        "planner": t.planner,
        "destination": t.destination,
        "notes": t.notes,
        "planned_arrival": t.planned_arrival,
        "arrived_at": t.arrived_at,
        "inspected_at": t.inspected_at,
        "planned_loading_start": t.planned_loading_start,
        "loading_started_at": t.loading_started_at,
        "planned_loading_end": t.planned_loading_end,
        "loading_ended_at": t.loading_ended_at,
        "planned_departure": t.planned_departure,
        "departed_at": t.departed_at,
        "loading_minutes": round(loading, 1) if loading is not None else None,
        "cycle_minutes": round(cycle, 1) if cycle is not None else None,
        "dispatch_day": rules.dispatch_day(t),
        "loading_day": rules.loading_day(t),
        "cycle_day": rules.cycle_day(t),
    }
    for checkpoint in Checkpoint:
        row[f"{checkpoint.value}_outcome"] = rules.checkpoint_outcome(t, checkpoint, config, now).value
        row[f"{checkpoint.value}_day"] = rules.checkpoint_day(t, checkpoint)
    return {column: row[column] for column in FACT_COLUMNS}      # in the stable column order


# ----------------------------------------------------------------- Small helpers

def _in_period(day: date | None, period: tuple[date, date]) -> bool:
    return day is not None and period[0] <= day <= period[1]


def _average(values: list[float]) -> float | None:
    """Average rounded to one decimal, or None when there is nothing to average."""
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return value.isoformat()
