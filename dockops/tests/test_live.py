"""
Tests for dockops.live. Each group follows a rule of docs/LIVE-BOARD.md.

"Now" is Wednesday 12 March 2025 at 10:00. With the demo configuration the week is
Monday 10 to Sunday 16 and the board looks back 5 days, to Friday 7.
"""
import json
from datetime import date, datetime

from dockops.live import build_live_payload
from dockops.models import CargoType, OpsConfig, Status, Transport

CONFIG = OpsConfig()
NOW = datetime(2025, 3, 12, 10, 0)


def at(day, hour, minute=0):
    return datetime(2025, 3, day, hour, minute)


def board(transports, now=NOW, config=CONFIG, **options):
    return build_live_payload(transports, now, config, **options)


def numbers(rows):
    return [row["number"] for row in rows]


def scheduled(number, day, hour=8, **fields):
    return Transport(number=number, planned_arrival=at(day, hour), **fields)


def dispatched(number, appointment_day, departed, **fields):
    return Transport(number=number, status=Status.DISPATCHED,
                     planned_arrival=at(appointment_day, 8), departed_at=departed, **fields)


def loading(number, started, bay=1, **fields):
    return Transport(number=number, status=Status.LOADING, bay=bay,
                     planned_arrival=at(12, 7), loading_started_at=started, **fields)


def timer_of(payload, bay=1):
    entry = next(b for b in payload["bays"] if b["bay"] == bay)
    return entry["transports"][0]["timer"]


# ----------------------------------------------------------------- The payload as a whole

def test_the_payload_is_plain_json():
    payload = board([scheduled("A", 12), loading("B", at(12, 9)), dispatched("C", 11, at(12, 8))],
                    data_updated_at=NOW)
    assert json.loads(json.dumps(payload)) == payload
    assert payload["generated_at"] == "2025-03-12T10:00:00"


def test_an_empty_board_still_has_every_section():
    payload = board([])
    assert payload["week"] == {"start": "2025-03-10", "end": "2025-03-16",
                               "dispatched": 0, "workload": 0, "completed": []}
    assert payload["status_chart"]["counts"] == []
    assert payload["loading_chart"]["days"] == []
    assert payload["adherence_chart"]["percent"] == [None] * 5
    assert [b["bay"] for b in payload["bays"]] == list(CONFIG.bays)
    assert payload["incoming"] == []


def test_data_is_stale_when_it_was_not_updated_recently():
    assert board([], data_updated_at=at(12, 9, 55))["data_is_stale"] is False
    assert board([], data_updated_at=at(12, 9, 45))["data_is_stale"] is True
    assert board([])["data_is_stale"] is True      # never updated


# ----------------------------------------------------------------- L1 · Board window

def test_the_board_ignores_appointments_older_than_the_carryover_limit():
    payload = board([scheduled("FIVE_DAYS", 7), scheduled("SIX_DAYS", 6)])
    assert numbers(payload["incoming"]) == ["FIVE_DAYS"]
    assert numbers(payload["status_chart"]["rows"]) == ["FIVE_DAYS"]


def test_a_transport_without_appointment_is_not_lost():
    payload = board([Transport(number="NO_DATE")])
    assert numbers(payload["incoming"]) == ["NO_DATE"]
    assert payload["incoming"][0]["group"] == "today"


# ----------------------------------------------------------------- L2 · Active operation

def test_the_active_operation_is_today_plus_the_carryovers():
    payload = board([
        scheduled("TODAY", 12),
        scheduled("MONDAY_NEVER_CAME", 10),
        Transport(number="TUESDAY_AT_BAY", status=Status.LOADING, bay=3, planned_arrival=at(11, 16)),
        dispatched("TUESDAY_LEFT_TODAY", 11, at(12, 8)),
        dispatched("MONDAY_LEFT_MONDAY", 10, at(10, 15)),
        scheduled("TOMORROW", 13),
    ])
    active = {"TODAY", "MONDAY_NEVER_CAME", "TUESDAY_AT_BAY", "TUESDAY_LEFT_TODAY"}
    assert set(numbers(payload["status_chart"]["rows"])) == active
    assert set(numbers(payload["adherence_chart"]["rows"])) == active


# ----------------------------------------------------------------- L3 · Week counter

def test_the_week_counts_dispatched_over_workload():
    payload = board([
        scheduled("THIS_WEEK", 14),
        dispatched("LEFT_MONDAY", 10, at(10, 15)),
        dispatched("FRIDAY_LEFT_MONDAY", 7, at(10, 9)),         # carryover dispatched this week
        Transport(number="SATURDAY_STILL_HERE", status=Status.LOADED, bay=2, planned_arrival=at(8, 8)),
        dispatched("LEFT_LAST_WEEK", 7, at(8, 12)),
        scheduled("NEXT_WEEK", 17),
    ])
    week = payload["week"]
    assert (week["dispatched"], week["workload"]) == (2, 4)
    assert set(numbers(week["completed"])) == {"LEFT_MONDAY", "FRIDAY_LEFT_MONDAY"}


def test_completed_transports_show_working_time_next_to_clock_time():
    overnight = dispatched("NIGHT", 10, at(11, 8),
                           arrived_at=at(10, 20), loading_started_at=at(10, 20, 30), loading_ended_at=at(11, 7, 30))
    row = board([overnight])["week"]["completed"][0]
    assert row["cycle"] == {"working_minutes": 120.0, "clock_minutes": 720.0}       # 20-21 + 07-08
    assert row["loading"] == {"working_minutes": 60.0, "clock_minutes": 660.0}
    assert board([dispatched("NO_TIMES", 10, at(11, 8))])["week"]["completed"][0]["loading"] is None


# ----------------------------------------------------------------- L4 · Status chart

def test_status_counts_follow_the_order_of_the_visit():
    payload = board([
        Transport(number="A", status=Status.LOADING, bay=1, planned_arrival=at(12, 8)),
        scheduled("B", 12), scheduled("C", 12),
        Transport(number="D", status=Status.WAITING, planned_arrival=at(12, 9)),
    ])
    assert payload["status_chart"]["counts"] == [
        {"status": "scheduled", "count": 2},
        {"status": "waiting", "count": 1},
        {"status": "loading", "count": 1},
    ]


# ----------------------------------------------------------------- L5 · Trend charts

def week_of_loadings():
    return [
        # dry, Monday: loading 2 h, cycle 4 h
        dispatched("DRY_MON", 10, at(10, 12), arrived_at=at(10, 8),
                   loading_started_at=at(10, 9), loading_ended_at=at(10, 11)),
        # dry, Tuesday: loading 2 h 20; it left on Wednesday, so its cycle counts on Wednesday
        dispatched("DRY_TUE", 11, at(12, 8), arrived_at=at(11, 15),
                   loading_started_at=at(11, 16), loading_ended_at=at(11, 18, 20)),
        # cold, Wednesday: loaded, still at its bay (no cycle yet)
        Transport(number="COLD_WED", status=Status.LOADED, bay=3, cargo_type=CargoType.COLD,
                  planned_arrival=at(12, 7), loading_started_at=at(12, 7, 30), loading_ended_at=at(12, 9, 30)),
        # last week: must not appear
        dispatched("LAST_WEEK", 7, at(7, 12), arrived_at=at(7, 8),
                   loading_started_at=at(7, 9), loading_ended_at=at(7, 10)),
    ]


def test_trends_average_each_day_of_the_week_that_has_measures():
    chart = board(week_of_loadings())["loading_chart"]
    assert chart["days"] == ["2025-03-10", "2025-03-11", "2025-03-12"]
    assert chart["daily_average"] == [120.0, 140.0, 120.0]
    assert chart["week_average"] == 126.7
    assert numbers(chart["rows"]) == ["DRY_MON", "DRY_TUE", "COLD_WED"]


def test_trends_are_split_by_cargo_type():
    by_type = board(week_of_loadings())["loading_chart"]["by_cargo_type"]
    assert by_type["dry"] == {"daily_average": [120.0, 140.0, None], "week_average": 130.0, "count": 2}
    assert by_type["cold"] == {"daily_average": [None, None, 120.0], "week_average": 120.0, "count": 1}


def test_a_cycle_counts_on_the_day_of_the_departure():
    chart = board(week_of_loadings())["cycle_chart"]
    assert chart["days"] == ["2025-03-10", "2025-03-11", "2025-03-12"]      # same axis as the loading chart
    assert chart["daily_average"] == [240.0, None, 420.0]                    # Tuesday 15-21 + Wednesday 07-08
    assert numbers(chart["rows"]) == ["DRY_MON", "DRY_TUE"]


# ----------------------------------------------------------------- L6 · Adherence chart

def test_adherence_has_one_percentage_per_checkpoint():
    on_time = Transport(number="A", status=Status.LOADING, bay=1,
                        planned_arrival=at(12, 8), arrived_at=at(12, 8, 5), inspected_at=at(12, 8, 20))
    late = Transport(number="B", status=Status.WAITING, cargo_type=CargoType.COLD,
                     planned_arrival=at(12, 8), arrived_at=at(12, 9))
    never_came = scheduled("C", 12)                  # appointment at 08:00, now 10:00: overdue
    chart = board([on_time, late, never_came])["adherence_chart"]

    assert chart["checkpoints"] == ["arrival", "inspection", "loading_start", "loading_end", "departure"]
    # arrival: 1 of 3 on time. inspection: A on time, B overdue. Nothing else can be judged yet.
    assert chart["percent"] == [33, 50, None, None, None]
    assert chart["by_cargo_type"]["cold"] == {"percent": [0, 0, None, None, None], "count": 1}
    assert chart["by_cargo_type"]["dry"]["count"] == 2


def test_adherence_rows_explain_each_outcome():
    transport = Transport(number="A", status=Status.WAITING,
                          planned_arrival=at(12, 8), arrived_at=at(12, 9))
    arrival, inspection = board([transport])["adherence_chart"]["rows"][0]["checkpoints"][:2]
    assert arrival == {"checkpoint": "arrival", "expected": "2025-03-12T08:00:00",
                       "deadline": "2025-03-12T08:15:00", "actual": "2025-03-12T09:00:00", "outcome": "late"}
    assert inspection["expected"] == "2025-03-12T09:00:00"      # the actual arrival
    assert inspection["deadline"] == "2025-03-12T09:20:00"
    assert inspection["outcome"] == "late"                      # not inspected, limit passed


# ----------------------------------------------------------------- L7 · Bays

def test_every_configured_bay_is_listed_and_free_ones_are_empty():
    payload = board([loading("A", at(12, 9), bay=3)])
    occupied = {b["bay"]: numbers(b["transports"]) for b in payload["bays"]}
    assert occupied == {1: [], 2: [], 3: ["A"], 4: [], 5: [], 6: [], 7: [], 8: []}
    assert all(b["is_configured"] for b in payload["bays"])


def test_a_waiting_transport_does_not_occupy_its_assigned_bay():
    waiting = Transport(number="W", status=Status.WAITING, bay=2, planned_arrival=at(12, 9), arrived_at=at(12, 9))
    payload = board([waiting])
    assert all(b["transports"] == [] for b in payload["bays"])
    assert payload["incoming"][0]["group"] == "waiting"


def test_a_transport_at_an_unknown_bay_gets_an_extra_entry():
    payload = board([loading("A", at(12, 9), bay=40), loading("B", at(12, 9), bay=None)])
    extras = [b for b in payload["bays"] if not b["is_configured"]]
    assert [(b["bay"], numbers(b["transports"])) for b in extras] == [(40, ["A"]), (None, ["B"])]


def test_a_carryover_at_a_bay_is_flagged():
    yesterday = Transport(number="A", status=Status.INSPECTED, bay=1, planned_arrival=at(11, 16))
    row = board([yesterday])["bays"][0]["transports"][0]
    assert row["is_carryover"] is True
    assert row["timer"]["state"] == "not_started"


# ----------------------------------------------------------------- L8 · Loading timer

def test_a_running_timer_is_compared_with_the_average_of_its_cargo_type():
    transports = week_of_loadings() + [loading("NOW", at(12, 9))]       # dry average this week: 130 min
    timer = timer_of(board(transports))
    assert timer == {"state": "running", "elapsed_seconds": 3600, "reference_minutes": 130.0,
                     "reference_kind": "average", "over_reference_minutes": -70.0,
                     "level": "ok", "paused_by": None}


def test_without_an_average_the_reference_is_the_fixed_limit():
    timer = timer_of(board([loading("NOW", at(12, 9), cargo_type=CargoType.COLD)]))
    assert (timer["reference_minutes"], timer["reference_kind"]) == (180, "limit")


def test_timer_levels():
    def level(started, now):
        return timer_of(board([loading("A", started)], now=now))["level"]

    assert level(at(12, 7), at(12, 9, 59)) == "ok"              # 179 min against the 180 limit
    assert level(at(12, 7), at(12, 10)) == "warning"            # reached the reference
    assert level(at(12, 7), at(12, 10, 45)) == "critical"       # 45 min over


def test_the_timer_pauses_in_the_break_unless_the_loading_started_in_it():
    paused = timer_of(board([loading("A", at(12, 12, 30))], now=at(12, 13, 20)))
    assert (paused["state"], paused["paused_by"], paused["elapsed_seconds"]) == ("paused", "break", 30 * 60)

    running = timer_of(board([loading("A", at(12, 13, 10))], now=at(12, 13, 40)))
    assert (running["state"], running["elapsed_seconds"]) == ("running", 30 * 60)


def test_the_timer_pauses_after_the_shift():
    timer = timer_of(board([loading("A", at(12, 20, 30))], now=at(12, 21, 30)))
    assert (timer["state"], timer["paused_by"], timer["elapsed_seconds"]) == ("paused", "off_shift", 30 * 60)


def test_a_finished_loading_shows_its_total_time():
    loaded = Transport(number="A", status=Status.LOADED, bay=1, planned_arrival=at(12, 7),
                       loading_started_at=at(12, 7, 30), loading_ended_at=at(12, 9))
    timer = timer_of(board([loaded]))
    assert (timer["state"], timer["elapsed_seconds"], timer["level"]) == ("finished", 90 * 60, None)


def test_missing_times_are_reported_instead_of_guessed():
    no_start = Transport(number="A", status=Status.LOADING, bay=1, planned_arrival=at(12, 7))
    no_end = Transport(number="B", status=Status.LOADED, bay=2, planned_arrival=at(12, 7),
                       loading_started_at=at(12, 8))
    payload = board([no_start, no_end])
    assert timer_of(payload, bay=1)["state"] == "missing_times"
    assert timer_of(payload, bay=2)["state"] == "missing_times"


# ----------------------------------------------------------------- Alerts (rule L10)

def alerts_of(transport, now=NOW):
    payload = board([transport], now=now)
    rows = [row for bay in payload["bays"] for row in bay["transports"]] + payload["incoming"]
    return rows[0]["alerts"]


def test_no_alert_when_everything_is_on_plan():
    calm = loading("A", at(12, 9), planned_loading_start=at(12, 9), planned_departure=at(12, 15))
    assert alerts_of(calm) == []


def test_alert_when_the_loading_start_is_late():
    assert "late_loading_start" in alerts_of(loading("A", at(12, 9, 30), planned_loading_start=at(12, 9)))
    not_started = Transport(number="B", status=Status.INSPECTED, bay=1,
                            planned_arrival=at(12, 8), planned_loading_start=at(12, 9))
    assert "late_loading_start" in alerts_of(not_started)       # overdue at 10:00


def test_alert_when_the_departure_is_near_or_passed():
    def with_departure(hour, minute=0):
        return scheduled("A", 12, hour=14, planned_departure=at(12, hour, minute))

    assert "departure_due" not in alerts_of(with_departure(11, 31))     # 91 min away
    assert "departure_due" in alerts_of(with_departure(11, 30))         # 90 min away
    assert "departure_due" in alerts_of(with_departure(9))              # already passed


def test_departure_overdue_is_flagged_on_the_row():
    payload = board([scheduled("A", 12, hour=14, planned_departure=at(12, 9))])
    assert payload["incoming"][0]["departure_overdue"] is True


def test_alert_when_the_loading_runs_well_over_its_reference():
    assert "loading_over_reference" not in alerts_of(loading("A", at(12, 7)), now=at(12, 10, 19))
    assert "loading_over_reference" in alerts_of(loading("A", at(12, 7)), now=at(12, 10, 20))    # 20 min over


# ----------------------------------------------------------------- L9 · Incoming

def test_incoming_groups():
    payload = board([
        scheduled("LATER_TODAY", 12, hour=14),
        scheduled("EARLIER", 10),
        scheduled("TOMORROW", 13),
        scheduled("IN_TWO_DAYS", 14),
        Transport(number="IN_YARD", status=Status.WAITING, planned_arrival=at(12, 9, 50), arrived_at=at(12, 9, 55)),
    ])
    groups = {row["number"]: row["group"] for row in payload["incoming"]}
    assert groups == {"LATER_TODAY": "today", "EARLIER": "earlier", "TOMORROW": "tomorrow", "IN_YARD": "waiting"}


def test_incoming_shows_late_arrivals_first_then_by_appointment():
    payload = board([
        scheduled("TOMORROW", 13),
        scheduled("LATER_TODAY", 12, hour=14),
        scheduled("MISSED_TODAY", 12, hour=8),
        scheduled("MISSED_MONDAY", 10),
        Transport(number="NO_DATE"),
    ])
    assert numbers(payload["incoming"]) == ["MISSED_MONDAY", "MISSED_TODAY", "LATER_TODAY", "TOMORROW", "NO_DATE"]
    assert [row["is_late"] for row in payload["incoming"]] == [True, True, False, False, False]


def test_dispatched_transports_are_neither_at_a_bay_nor_incoming():
    payload = board([dispatched("GONE", 12, at(12, 9), bay=1)])
    assert payload["incoming"] == []
    assert all(b["transports"] == [] for b in payload["bays"])


def test_board_rows_carry_the_detail_of_the_transport():
    transport = scheduled("A", 12, carrier="Northwind Haulage", planner="R. Vega", destination="Port Aster",
                          booking_ref="BK-1001", seal_number="S-77", notes="Fragile")
    row = board([transport])["incoming"][0]
    assert row["notes"] == "Fragile"
    assert row["detail"]["carrier"] == "Northwind Haulage"
    assert len(row["detail"]["checkpoints"]) == 5
    assert row["appointment"] == "2025-03-12T08:00:00"
    assert row["arrival_outcome"] == "late"
