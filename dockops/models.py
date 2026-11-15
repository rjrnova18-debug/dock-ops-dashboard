"""
The data of the dock operation: what a transport is and how the operation is configured.

Nothing here calculates anything. The rules that use this data live in rules.py.
The vocabulary (transport, bay, checkpoint, outcome...) is defined in GLOSSARY.md.
"""
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum


class Status(Enum):
    """The stage of the visit a transport is in, in the order it normally advances."""
    SCHEDULED = "scheduled"      # has an appointment, has not arrived
    WAITING = "waiting"          # arrived, waiting in the yard
    INSPECTED = "inspected"      # at its bay, inspection done
    LOADING = "loading"          # at its bay, loading in progress
    LOADED = "loaded"            # at its bay, loading finished, waiting to leave
    DISPATCHED = "dispatched"    # left the distribution center
    IN_TRANSIT = "in_transit"    # on the road
    DELIVERED = "delivered"      # route finished


# Statuses in which the transport physically occupies its bay. A WAITING transport may
# already have a bay assigned, but it is still in the yard: the bay is free.
AT_BAY_STATUSES = frozenset({Status.INSPECTED, Status.LOADING, Status.LOADED})

# Statuses of a transport that has already left the distribution center.
DISPATCHED_STATUSES = frozenset({Status.DISPATCHED, Status.IN_TRANSIT, Status.DELIVERED})


class CargoType(Enum):
    """What the transport carries. Cold loads take longer, so averages are kept per type."""
    DRY = "dry"
    COLD = "cold"


class Checkpoint(Enum):
    """The five moments of a visit that are compared against the plan."""
    ARRIVAL = "arrival"
    INSPECTION = "inspection"
    LOADING_START = "loading_start"
    LOADING_END = "loading_end"
    DEPARTURE = "departure"


class Outcome(Enum):
    """The result of comparing a checkpoint with its expected time."""
    ON_TIME = "on_time"    # happened within the tolerance
    LATE = "late"          # happened after the tolerance, or is overdue
    PENDING = "pending"    # has not happened and is not overdue yet
    NO_PLAN = "no_plan"    # happened, but there is no expected time to compare with


@dataclass(frozen=True)
class OpsConfig:
    """
    How the operation works: tolerances, the shift and the bays.

    The defaults are demo values. Every rule receives the config as a parameter, so a
    different operation only needs a different OpsConfig, never a code change.
    """
    tolerance_minutes: int = 15            # delay allowed before a checkpoint counts as late
    inspection_limit_minutes: int = 20     # longest an inspection may take after arrival

    shift_start: time = time(7, 0)
    shift_end: time = time(21, 0)
    break_start: time = time(13, 0)
    break_end: time = time(14, 0)
    rest_weekday: int | None = 6           # date.weekday(): Monday = 0 ... Sunday = 6; None = no rest day
    week_start_weekday: int = 0            # the weekday a reporting week starts on

    carryover_days: int = 5                # how many days back a pending transport still counts
    bays: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8)

    # Live board: the clock of a loading in progress and the row alerts
    loading_limit_minutes: int = 180       # loading reference while a cargo type has no average yet
    critical_excess_minutes: int = 45      # minutes over the reference at which the clock turns critical
    alert_excess_minutes: int = 20         # minutes over the reference at which the row is highlighted
    departure_warning_minutes: int = 90    # highlight the row this long before the planned departure
    stale_after_minutes: int = 10          # data older than this is shown as out of date

    def __post_init__(self):
        in_order = self.shift_start < self.break_start < self.break_end < self.shift_end
        if not in_order:
            raise ValueError("Expected shift_start < break_start < break_end < shift_end.")


@dataclass
class Transport:
    """
    One vehicle visit, from its appointment to its departure.

    Each checkpoint has a planned time and an actual time. A time that is None means
    "not planned" or "has not happened yet". Inspection has no planned time of its own:
    it is expected within the inspection limit after the actual arrival.
    """
    number: str
    status: Status = Status.SCHEDULED
    cargo_type: CargoType = CargoType.DRY
    bay: int | None = None

    planned_arrival: datetime | None = None          # the appointment
    arrived_at: datetime | None = None
    inspected_at: datetime | None = None
    planned_loading_start: datetime | None = None
    loading_started_at: datetime | None = None
    planned_loading_end: datetime | None = None
    loading_ended_at: datetime | None = None
    planned_departure: datetime | None = None
    departed_at: datetime | None = None

    carrier: str = ""
    planner: str = ""
    destination: str = ""
    booking_ref: str = ""
    seal_number: str = ""
    notes: str = ""

    @property
    def is_dispatched(self) -> bool:
        return self.status in DISPATCHED_STATUSES

    @property
    def is_at_bay(self) -> bool:
        return self.status in AT_BAY_STATUSES

    @property
    def appointment_day(self) -> date | None:
        return self.planned_arrival.date() if self.planned_arrival else None
