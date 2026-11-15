"""
Tests for dockops.history. Each group follows a rule of docs/HISTORY.md.

The main scenario is September 2025 (the 1st is a Monday), looked at from 28 October,
with the demo configuration: tolerance 15 min, inspection limit 20 min, shift
07:00-21:00 with the break at 13:00-14:00, weeks from Monday, carryover 5 days.
"""
import json
from datetime import date, datetime, timedelta

import pytest

from dockops.history import FACT_COLUMNS, TOP_LOADINGS, build_history_summary, fact_rows
from dockops.live import build_live_payload
from dockops.models import CargoType, OpsConfig, Status, Transport

CONFIG = OpsConfig()
NOW = datetime(2025, 10, 28, 10, 0)
SEPTEMBER = (date(2025, 9, 1), date(2025, 9, 30))


def visit(number, appointment, cargo_type=CargoType.DRY, status=Status.DISPATCHED, **actual):
    """A transport planned like the demo data: loading starts 1 h after the appointment,
    ends at +3 h (cold: +4 h) and the transport leaves at +4 h (cold: +5 h)."""
    extra = 1 if cargo_type is CargoType.COLD else 0
    return Transport(
        number=number, status=status, cargo_type=cargo_type, bay=3, carrier="Northwind Haulage",
        planned_arrival=appointment,
        planned_loading_start=appointment + timedelta(hours=1),
        planned_loading_end=appointment + timedelta(hours=3 + extra),
        planned_departure=appointment + timedelta(hours=4 + extra),
        **actual,
    )


def sep(day, hour, minute=0):
    return datetime(2025, 9, day, hour, minute)


# A: dry, everything on time. Loading 2 h, cycle 08:05 -> 12:00.
A = visit("A", sep(1, 8), arrived_at=sep(1, 8, 5), inspected_at=sep(1, 8, 20),
          loading_started_at=sep(1, 9), loading_ended_at=sep(1, 11), departed_at=sep(1, 12))
# B: cold, everything late. Loading 10:00 -> 14:30 = 3.5 h of working time (the break is crossed).
B = visit("B", sep(2, 8), CargoType.COLD, arrived_at=sep(2, 9), inspected_at=sep(2, 9, 50),
          loading_started_at=sep(2, 10), loading_ended_at=sep(2, 14, 30), departed_at=sep(2, 15))
# C: dry, never arrived and nobody closed it.
C = visit("C", sep(3, 8), status=Status.SCHEDULED)
# D: outside the period.
D = visit("D", datetime(2025, 10, 15, 8), status=Status.WAITING, arrived_at=datetime(2025, 10, 15, 8))
# E: appointment on 31 August, but it arrived and left on 1 September.
E = visit("E", datetime(2025, 8, 31, 8), arrived_at=sep(1, 7, 30), departed_at=sep(1, 12))

ALL = [A, B, C, D, E]


def summary(transports=ALL, period=SEPTEMBER, now=NOW, **options):
    return build_history_summary(transports, *period, now, CONFIG, **options)


# ----------------------------------------------------------------- The summary as a whole

def test_the_summary_is_plain_json():
    result = summary()
    assert json.loads(json.dumps(result)) == result
    assert (result["period_start"], result["period_end"]) == ("2025-09-01", "2025-09-30")
    assert (result["group_by"], result["cargo_type"]) == ("week", None)


def test_an_unknown_grouping_is_rejected():
    with pytest.raises(ValueError):
        summary(group_by="quarter")


def test_an_empty_period_still_has_every_section():
    result = summary(period=(date(2020, 1, 1), date(2020, 1, 31)))
    assert result["totals"]["appointments"] == 0
    assert result["totals"]["loading_average_minutes"] is None
    assert (result["series"], result["slowest_loadings"]) == ([], [])
    assert len(result["activity"]) == 31


# ----------------------------------------------------------------- H1, H2 · Totals

def test_totals_count_each_thing_on_the_day_it_happened():
    totals = summary()["totals"]
    # appointments in September: A, B, C. Dispatched in September: A, B and E.
    # workload: A, B, C plus E (a carryover from 31 August dispatched on 1 September)
    assert (totals["appointments"], totals["dispatched"], totals["workload"]) == (3, 3, 4)
    assert (totals["loading_average_minutes"], totals["loading_count"]) == (165.0, 2)     # 120 and 210
    assert (totals["cycle_average_minutes"], totals["cycle_count"]) == (268.3, 3)         # 235, 300, 270
    assert totals["adherence_percent"] == 33


def test_totals_per_cargo_type():
    by_type = summary()["by_cargo_type"]
    assert (by_type["dry"]["appointments"], by_type["dry"]["workload"]) == (2, 3)
    assert by_type["cold"]["dispatched"] == 1
    assert by_type["cold"]["loading_average_minutes"] == 210.0


def test_the_cargo_type_filter_leaves_only_that_type():
    result = summary(cargo_type=CargoType.COLD)
    assert result["cargo_type"] == "cold"
    assert result["totals"]["appointments"] == 1
    assert result["by_cargo_type"]["dry"]["appointments"] == 0
    assert result["unclosed"]["total"] == 0
    assert sum(day["arrivals"] for day in result["activity"]) == 1       # only B


# ----------------------------------------------------------------- H3 · Series

def test_series_by_week_month_and_day():
    assert [bucket["key"] for bucket in summary(group_by="week")["series"]] == ["2025-09-01"]
    months = summary(group_by="month")["series"]
    assert [(bucket["key"], bucket["appointments"]) for bucket in months] == [("2025-09", 3)]
    days = summary(group_by="day")["series"]
    assert [bucket["key"] for bucket in days] == ["2025-09-01", "2025-09-02", "2025-09-03"]


def test_each_bucket_is_split_by_cargo_type():
    first_day, second_day = summary(group_by="day")["series"][:2]
    assert first_day["dispatched"] == 2                                   # A and E
    assert first_day["by_cargo_type"]["cold"]["dispatched"] == 0
    assert second_day["by_cargo_type"]["cold"]["loading_average_minutes"] == 210.0
    assert second_day["by_cargo_type"]["dry"]["loading_count"] == 0


def test_the_series_adds_up_to_the_totals():
    result = summary(group_by="day")
    for name in ("appointments", "dispatched", "loading_count", "cycle_count"):
        assert sum(bucket[name] for bucket in result["series"]) == result["totals"][name]


# ----------------------------------------------------------------- H4 · Checkpoints

def test_checkpoints_use_the_same_rules_as_the_live_board():
    by_checkpoint = {row["checkpoint"]: row for row in summary()["checkpoints"]}
    # arrival counts on the appointment day: A on time, B late, C overdue. E's was in August.
    arrival = by_checkpoint["arrival"]
    assert (arrival["on_time"], arrival["late"], arrival["percent"]) == (1, 2, 33)
    assert arrival["by_cargo_type"] == {"dry": 50, "cold": 0}
    # inspection counts on the day of the actual arrival: A on time, B took 50 min,
    # E arrived on the 1st and was never inspected. C never arrived, so it does not count.
    inspection = by_checkpoint["inspection"]
    assert (inspection["on_time"], inspection["late"], inspection["pending"]) == (1, 2, 0)


def test_checkpoints_keep_pending_and_no_plan_apart():
    not_yet = visit("F", sep(20, 8), status=Status.WAITING, arrived_at=sep(20, 8))
    unplanned = Transport(number="G", status=Status.DISPATCHED, departed_at=sep(20, 15))
    result = summary([not_yet, unplanned], now=sep(20, 8, 30))
    departure = {row["checkpoint"]: row for row in result["checkpoints"]}["departure"]
    assert (departure["pending"], departure["no_plan"], departure["percent"]) == (1, 1, None)


# ----------------------------------------------------------------- H5 · Activity calendar

def test_activity_counts_by_the_real_day_of_arrival_and_departure():
    activity = {day["day"]: day for day in summary()["activity"]}
    assert len(activity) == 30
    # A and E arrived on the 1st (E's appointment was on 31 August)
    assert [activity[f"2025-09-0{n}"]["arrivals"] for n in (1, 2, 3)] == [2, 1, 0]
    assert [activity[f"2025-09-0{n}"]["departures"] for n in (1, 2)] == [2, 1]


# ----------------------------------------------------------------- H6, H7 · Loadings and unclosed

def test_slowest_and_fastest_loadings_come_with_their_detail():
    result = summary()
    assert [row["number"] for row in result["slowest_loadings"]] == ["B", "A"]
    assert result["fastest_loadings"][0]["number"] == "A"
    slowest = result["slowest_loadings"][0]
    assert (slowest["loading_minutes"], slowest["cycle_minutes"]) == (210.0, 300.0)
    assert len(slowest["detail"]["checkpoints"]) == 5


def test_only_the_top_loadings_are_listed():
    many = [visit(f"T{n}", sep(1, 8), arrived_at=sep(1, 8), loading_started_at=sep(1, 9),
                  loading_ended_at=sep(1, 9, 30 + n), departed_at=sep(1, 12)) for n in range(15)]
    result = summary(many)
    assert len(result["slowest_loadings"]) == TOP_LOADINGS
    assert result["slowest_loadings"][0]["number"] == "T14"
    assert result["fastest_loadings"][0]["number"] == "T0"


def test_unclosed_lists_what_was_never_dispatched_and_left_the_board():
    unclosed = summary()["unclosed"]
    assert (unclosed["total"], unclosed["rows"][0]["number"]) == (1, "C")


def test_a_recent_pending_transport_is_not_unclosed_yet():
    # seen on 5 September, C (appointment on the 3rd) is still on the live board
    assert summary(now=sep(5, 10))["unclosed"]["total"] == 0


# ----------------------------------------------------------------- H8 · Fact table

def test_fact_rows_have_stable_columns_and_only_the_period():
    rows = fact_rows(ALL, *SEPTEMBER, NOW, CONFIG)
    assert [row["number"] for row in rows] == ["A", "B", "C", "E"]
    assert all(tuple(row) == FACT_COLUMNS for row in rows)


def test_fact_rows_say_on_which_day_each_thing_counts():
    rows = {row["number"]: row for row in fact_rows(ALL, *SEPTEMBER, NOW, CONFIG)}
    e = rows["E"]
    assert (e["dispatch_day"], e["cycle_day"], e["arrival_day"]) == (date(2025, 9, 1), date(2025, 9, 1), date(2025, 8, 31))
    b = rows["B"]
    assert (b["cargo_type"], b["week_start"], b["weekday"], b["year"], b["month"]) == (
        "cold", date(2025, 9, 1), "Tuesday", 2025, 9)
    assert (b["loading_minutes"], b["arrival_outcome"], b["is_dispatched"]) == (210.0, "late", True)


def test_fact_rows_can_be_filtered_by_cargo_type():
    rows = fact_rows(ALL, *SEPTEMBER, NOW, CONFIG, cargo_type=CargoType.COLD)
    assert [row["number"] for row in rows] == ["B"]


# ----------------------------------------------------------------- Indicator days across weeks

def test_friday_to_monday_counts_the_loading_on_friday_and_the_rest_on_monday():
    transport = visit("FM", sep(5, 8), arrived_at=sep(5, 8), inspected_at=sep(5, 8, 15),
                      loading_started_at=sep(5, 9), loading_ended_at=sep(5, 11), departed_at=sep(8, 9))
    first_week = summary([transport], period=(date(2025, 9, 1), date(2025, 9, 7)))["totals"]
    second_week = summary([transport], period=(date(2025, 9, 8), date(2025, 9, 14)))["totals"]

    assert (first_week["loading_count"], first_week["dispatched"], first_week["cycle_count"]) == (1, 0, 0)
    assert (second_week["loading_count"], second_week["dispatched"], second_week["cycle_count"]) == (0, 1, 1)
    assert (first_week["appointments"], second_week["appointments"]) == (1, 0)
    assert (first_week["workload"], second_week["workload"]) == (1, 1)       # a carryover on the second week
    # Friday 08:00 -> Monday 09:00 in working time, Sunday skipped: 12 h + 13 h + 2 h
    assert second_week["cycle_average_minutes"] == 27 * 60


# ----------------------------------------------------------------- H9 · Agreement with the live board

def test_the_live_board_and_the_history_agree_on_the_same_week():
    week = (date(2025, 9, 1), date(2025, 9, 7))
    sunday_evening = sep(7, 20)
    live = build_live_payload(ALL, sunday_evening, CONFIG)
    totals = build_history_summary(ALL, *week, sunday_evening, CONFIG)["totals"]

    assert (live["week"]["dispatched"], live["week"]["workload"]) == (totals["dispatched"], totals["workload"])
    assert len(live["loading_chart"]["rows"]) == totals["loading_count"]
    assert len(live["cycle_chart"]["rows"]) == totals["cycle_count"]
    assert live["loading_chart"]["week_average"] == totals["loading_average_minutes"]
