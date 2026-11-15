"""
Tests for dockops.rules. Each group follows a section of docs/RULES.md.

All tests use the demo configuration:
    shift 07:00-21:00, break 13:00-14:00 (13 working hours a day), rest day Sunday,
    weeks start on Monday, tolerance 15 min, inspection limit 20 min, carryover 5 days.
"""
from dataclasses import replace
from datetime import date, datetime, timedelta

from dockops.models import Checkpoint, OpsConfig, Outcome, Status, Transport
from dockops.rules import (
    adherence_percent,
    checkpoint_day,
    checkpoint_outcome,
    compare_with_expected,
    cycle_day,
    cycle_minutes,
    dispatch_day,
    in_workload,
    is_loading_clock_running,
    loading_day,
    loading_minutes,
    loading_minutes_so_far,
    week_of,
    working_minutes,
)

CONFIG = OpsConfig()
FULL_DAY = 13 * 60

# March 2025: Wednesday 12, Friday 14, Saturday 15, Sunday 16, Monday 17
WED, FRI, SAT, SUN, MON = (date(2025, 3, d) for d in (12, 14, 15, 16, 17))


def at(hour, minute=0, day=WED):
    return datetime(day.year, day.month, day.day, hour, minute)


# ----------------------------------------------------------------- 1. Working time

def worked(start, end, config=CONFIG):
    return working_minutes(start, end, config)


def test_the_break_is_not_working_time():
    assert worked(at(12, 30), at(14, 30)) == 60      # 30 before + 30 after
    assert worked(at(11), at(13)) == 120             # ends exactly when the break starts
    assert worked(at(14), at(16)) == 120             # starts exactly when the break ends
    assert worked(at(13, 15), at(13, 45)) == 0       # entirely inside the break


def test_time_outside_the_shift_is_not_working_time():
    assert worked(at(5), at(8)) == 60                # counts from 07:00
    assert worked(at(21, 10), at(21, 50)) == 0
    assert worked(at(23), at(5, day=WED + timedelta(days=1))) == 0


def test_a_range_over_several_days_adds_each_day():
    thursday = WED + timedelta(days=1)
    assert worked(at(20), at(9, day=thursday)) == 60 + 120      # 20-21 + 07-09
    assert worked(at(0), at(23, 59)) == FULL_DAY
    assert worked(at(7), at(21, day=FRI)) == 3 * FULL_DAY       # one break per day


def test_missing_or_backwards_ranges_have_no_duration():
    assert worked(None, at(9)) is None
    assert worked(at(9), None) is None
    assert worked(at(10), at(9)) is None


def test_a_rest_day_in_the_middle_is_skipped():
    # Friday 16:00 -> Monday 09:00: Friday 5 h + Saturday 13 h + Monday 2 h
    assert worked(at(16, day=FRI), at(9, day=MON)) == (5 + 13 + 2) * 60


def test_a_rest_day_counts_when_the_range_starts_or_ends_on_it():
    assert worked(at(8, day=SUN), at(11, day=SUN)) == 180
    assert worked(at(20, day=SAT), at(9, day=SUN)) == 60 + 120
    assert worked(at(10, day=SUN), at(8, day=MON)) == (3 + 7 + 1) * 60


def test_without_a_rest_day_every_day_counts():
    every_day = OpsConfig(rest_weekday=None)
    assert worked(at(16, day=FRI), at(9, day=MON), every_day) == (5 + 13 + 13 + 2) * 60


def loaded(start, end):
    return working_minutes(start, end, CONFIG, count_activity=True)


def test_activity_rule_counts_the_break_when_loading_starts_or_ends_in_it():
    assert loaded(at(13, 15), at(13, 45)) == 30      # all of it inside the break
    assert loaded(at(13), at(13, 30)) == 30          # starts as the break starts
    assert loaded(at(12, 30), at(13, 40)) == 70      # ends inside the break
    assert loaded(at(13, 20), at(15)) == 100         # starts inside the break


def test_activity_rule_does_not_count_a_break_that_is_only_crossed():
    assert loaded(at(12, 30), at(14, 30)) == 60
    assert loaded(at(12), at(14)) == 60              # ending exactly at 14:00 is not "inside"


def test_activity_rule_counts_time_outside_the_shift():
    thursday = WED + timedelta(days=1)
    assert loaded(at(21, 10), at(21, 50)) == 40      # all of it after the shift
    assert loaded(at(20, 30), at(21, 40)) == 70      # ends after the shift
    assert loaded(at(4, 30), at(5, 15)) == 45        # all of it before the shift
    assert loaded(at(6), at(8)) == 120               # starts before the shift
    assert loaded(at(20), at(21)) == 60              # ending exactly at 21:00 is not "inside"
    assert loaded(at(23), at(1, day=thursday)) == 120


def test_activity_rule_looks_at_each_idle_period_separately():
    thursday = WED + timedelta(days=1)
    # Starts Wednesday night (counts) and ends Thursday at 08:00, inside the shift:
    # Thursday's early hours had no start or end in them, so they do not count.
    assert loaded(at(23), at(8, day=thursday)) == 60 + 60
    assert loaded(at(20), at(9, day=thursday)) == 60 + 120     # only crosses the night


def in_progress(start, now):
    return working_minutes(start, now, CONFIG, count_activity=True, end_is_now=True)


def test_now_is_not_proof_of_activity():
    assert in_progress(at(12, 30), at(13, 20)) == 30     # paused during the break
    assert in_progress(at(20, 30), at(21, 30)) == 30     # paused after the shift
    # ...but a loading that started inside the idle period keeps running
    assert in_progress(at(13, 10), at(13, 40)) == 30
    assert in_progress(at(13, 10), at(15)) == 110
    assert in_progress(at(21, 10), at(22)) == 50


def test_the_loading_clock_runs_in_working_time_and_pauses_in_idle_periods():
    assert is_loading_clock_running(at(9), at(10), CONFIG)                   # in the shift
    assert not is_loading_clock_running(at(12, 30), at(13, 20), CONFIG)      # in the break
    assert not is_loading_clock_running(at(20, 30), at(21, 30), CONFIG)      # after the shift
    # ...but it keeps running if the loading started inside that same idle period
    assert is_loading_clock_running(at(13, 10), at(13, 40), CONFIG)
    assert is_loading_clock_running(at(21, 10), at(22), CONFIG)
    # a loading from last night is paused in today's early hours: a different idle period
    thursday = WED + timedelta(days=1)
    assert not is_loading_clock_running(at(22), at(3, day=thursday), CONFIG)


def test_loading_time_so_far_is_never_negative():
    assert loading_minutes_so_far(at(9), at(10), CONFIG) == 60
    assert loading_minutes_so_far(at(11), at(10), CONFIG) == 0       # start ahead of the clock


def test_loading_uses_the_activity_rule_and_the_cycle_does_not():
    transport = Transport(
        number="T-1",
        arrived_at=at(13, 15), departed_at=at(13, 45),
        loading_started_at=at(13, 15), loading_ended_at=at(13, 45),
    )
    assert loading_minutes(transport, CONFIG) == 30
    assert cycle_minutes(transport, CONFIG) == 0
    assert loading_minutes(Transport(number="T-2"), CONFIG) is None


# ----------------------------------------------------------------- 2. Checkpoints

def test_on_time_up_to_the_tolerance():
    assert compare_with_expected(at(10), at(9, 40), 15) is Outcome.ON_TIME      # early
    assert compare_with_expected(at(10), at(10, 15), 15) is Outcome.ON_TIME     # exactly at the limit
    assert compare_with_expected(at(10), at(10, 16), 15) is Outcome.LATE


def test_not_happened_yet_is_pending_until_it_is_overdue():
    assert compare_with_expected(at(10), None, 15) is Outcome.PENDING                     # no clock given
    assert compare_with_expected(at(10), None, 15, now=at(10, 15)) is Outcome.PENDING
    assert compare_with_expected(at(10), None, 15, now=at(10, 16)) is Outcome.LATE        # overdue


def test_without_an_expected_time_there_is_nothing_to_compare():
    assert compare_with_expected(None, at(10), 15) is Outcome.NO_PLAN
    assert compare_with_expected(None, None, 15, now=at(12)) is Outcome.PENDING


def test_each_checkpoint_compares_its_own_times():
    transport = Transport(
        number="T-1",
        planned_arrival=at(8), arrived_at=at(8, 10),                        # on time
        planned_loading_start=at(9), loading_started_at=at(9, 30),          # late
        planned_loading_end=at(11),                                         # not happened
        departed_at=at(12),                                                 # happened, never planned
    )
    now = at(10)
    assert checkpoint_outcome(transport, Checkpoint.ARRIVAL, CONFIG, now) is Outcome.ON_TIME
    assert checkpoint_outcome(transport, Checkpoint.LOADING_START, CONFIG, now) is Outcome.LATE
    assert checkpoint_outcome(transport, Checkpoint.LOADING_END, CONFIG, now) is Outcome.PENDING
    assert checkpoint_outcome(transport, Checkpoint.DEPARTURE, CONFIG, now) is Outcome.NO_PLAN


def test_inspection_is_expected_within_its_limit_after_the_actual_arrival():
    arrived = Transport(number="T-1", arrived_at=at(10))

    def inspection(transport, now=None):
        return checkpoint_outcome(transport, Checkpoint.INSPECTION, CONFIG, now)

    assert inspection(replace(arrived, inspected_at=at(10, 20))) is Outcome.ON_TIME
    assert inspection(replace(arrived, inspected_at=at(10, 21))) is Outcome.LATE
    assert inspection(arrived, now=at(10, 20)) is Outcome.PENDING
    assert inspection(arrived, now=at(10, 21)) is Outcome.LATE                      # overdue
    assert inspection(Transport(number="T-2", inspected_at=at(10))) is Outcome.NO_PLAN   # no arrival recorded
    assert inspection(Transport(number="T-3"), now=at(12)) is Outcome.PENDING


def test_adherence_only_judges_on_time_and_late():
    outcomes = [Outcome.ON_TIME, Outcome.ON_TIME, Outcome.LATE, Outcome.PENDING, Outcome.NO_PLAN]
    assert adherence_percent(outcomes) == 67
    assert adherence_percent([Outcome.LATE]) == 0


def test_adherence_is_none_when_nothing_can_be_judged():
    assert adherence_percent([]) is None
    assert adherence_percent([Outcome.PENDING, Outcome.NO_PLAN]) is None


# ----------------------------------------------------------------- 3. Indicator days

# Arrived and loaded on Friday, left on Monday.
FRIDAY_TO_MONDAY = Transport(
    number="T-1",
    status=Status.DISPATCHED,
    planned_arrival=at(8, day=FRI), arrived_at=at(8, 5, day=FRI),
    inspected_at=at(8, 20, day=FRI),
    planned_loading_start=at(9, day=FRI), loading_started_at=at(9, day=FRI),
    planned_loading_end=at(11, day=FRI), loading_ended_at=at(11, day=FRI),
    planned_departure=at(12, day=FRI), departed_at=at(10, day=MON),
)


def test_each_indicator_counts_on_the_day_it_happened():
    assert loading_day(FRIDAY_TO_MONDAY) == FRI      # loaded on Friday
    assert dispatch_day(FRIDAY_TO_MONDAY) == MON     # left on Monday
    assert cycle_day(FRIDAY_TO_MONDAY) == MON        # the cycle closes with the departure


def test_dispatched_without_a_departure_time_counts_on_its_appointment_day():
    assert dispatch_day(replace(FRIDAY_TO_MONDAY, departed_at=None)) == FRI


def test_a_transport_that_has_not_left_has_no_dispatch_day():
    assert dispatch_day(replace(FRIDAY_TO_MONDAY, status=Status.LOADED)) is None


def test_incomplete_loadings_and_cycles_have_no_day():
    assert loading_day(replace(FRIDAY_TO_MONDAY, loading_started_at=None)) is None
    assert loading_day(replace(FRIDAY_TO_MONDAY, loading_ended_at=None)) is None
    assert cycle_day(replace(FRIDAY_TO_MONDAY, arrived_at=None)) is None


def test_a_checkpoint_counts_on_the_day_it_was_expected():
    planned_for_monday = replace(FRIDAY_TO_MONDAY, planned_departure=at(9, day=MON))
    assert checkpoint_day(planned_for_monday, Checkpoint.DEPARTURE) == MON
    assert checkpoint_day(planned_for_monday, Checkpoint.ARRIVAL) == FRI
    assert checkpoint_day(planned_for_monday, Checkpoint.INSPECTION) == FRI      # expected from the arrival


def test_a_checkpoint_without_expected_time_counts_on_the_day_it_happened():
    unplanned = replace(FRIDAY_TO_MONDAY, planned_departure=None)
    assert checkpoint_day(unplanned, Checkpoint.DEPARTURE) == MON
    assert checkpoint_day(Transport(number="T-2"), Checkpoint.DEPARTURE) is None


def test_week_of():
    assert week_of(WED, CONFIG) == (date(2025, 3, 10), SUN)          # Monday to Sunday
    assert week_of(SUN, CONFIG) == (date(2025, 3, 10), SUN)
    assert week_of(MON, CONFIG) == (MON, date(2025, 3, 23))
    sunday_weeks = OpsConfig(week_start_weekday=6)
    assert week_of(WED, sunday_weeks) == (date(2025, 3, 9), SAT)     # Sunday to Saturday


WEEK = (MON, date(2025, 3, 23))      # Monday 17 to Sunday 23


def scheduled_for(day):
    return Transport(number="T-9", planned_arrival=at(8, day=day))


def test_workload_includes_appointments_of_the_period():
    assert in_workload(scheduled_for(date(2025, 3, 19)), *WEEK, CONFIG)
    assert not in_workload(scheduled_for(date(2025, 3, 24)), *WEEK, CONFIG)     # next week


def test_workload_includes_what_was_dispatched_in_the_period():
    assert in_workload(FRIDAY_TO_MONDAY, *WEEK, CONFIG)      # Friday's appointment, left on Monday


def test_workload_includes_carryovers_still_pending():
    still_here = replace(FRIDAY_TO_MONDAY, status=Status.LOADED, departed_at=None)
    assert in_workload(still_here, *WEEK, CONFIG)


def test_workload_excludes_what_left_before_the_period():
    left_on_saturday = replace(FRIDAY_TO_MONDAY, departed_at=at(10, day=SAT))
    assert not in_workload(left_on_saturday, *WEEK, CONFIG)


def test_workload_excludes_carryovers_older_than_the_limit():
    # carryover_days = 5: the oldest appointment that still counts is Wednesday 12
    assert in_workload(scheduled_for(WED), *WEEK, CONFIG)
    assert not in_workload(scheduled_for(date(2025, 3, 11)), *WEEK, CONFIG)


def test_workload_excludes_transports_without_appointment_or_dispatch():
    assert not in_workload(Transport(number="T-2"), *WEEK, CONFIG)
