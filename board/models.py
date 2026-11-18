"""
The database side of a transport, and the bridge to the domain.

dockops works with plain dataclasses in local time without a time zone; Django stores
date-times in UTC with a zone. This module is the only place that converts between the
two: views load rows here, call to_domain(), and hand dataclasses to dockops.
"""
from datetime import date, datetime, timedelta

from django.db import models
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from dockops.live import LOOKBACK_DAYS
from dockops.models import CargoType, Status
from dockops.models import Transport as DomainTransport

# The enums of dockops are the single source of truth for the stored values.
# Only the labels (shown in the admin) live here, so they can be translated.
STATUS_LABELS = {
    Status.SCHEDULED: _("Scheduled"),
    Status.WAITING: _("Waiting"),
    Status.INSPECTED: _("Inspected"),
    Status.LOADING: _("Loading"),
    Status.LOADED: _("Loaded"),
    Status.DISPATCHED: _("Dispatched"),
    Status.IN_TRANSIT: _("In transit"),
    Status.DELIVERED: _("Delivered"),
}
CARGO_TYPE_LABELS = {
    CargoType.DRY: _("Dry"),
    CargoType.COLD: _("Cold"),
}
STATUS_CHOICES = [(status.value, STATUS_LABELS[status]) for status in Status]
CARGO_TYPE_CHOICES = [(cargo.value, CARGO_TYPE_LABELS[cargo]) for cargo in CargoType]

# Fields copied one to one between the model and the dataclass.
TIME_FIELDS = (
    "planned_arrival", "arrived_at", "inspected_at",
    "planned_loading_start", "loading_started_at",
    "planned_loading_end", "loading_ended_at",
    "planned_departure", "departed_at",
)
TEXT_FIELDS = ("carrier", "planner", "destination", "booking_ref", "seal_number", "notes")

# Access to the history page: a permission on Transport, given through a group that the
# data migration 0002 creates. The history app checks HISTORY_PERMISSION.
HISTORY_PERMISSION = "board.view_history"
HISTORY_VIEWERS_GROUP = "History viewers"


# ------------------------------------------------------------------- Time zone bridge

def to_local_naive(moment: datetime | None) -> datetime | None:
    """A stored (aware, UTC) date-time as the operation's local time without a zone."""
    if moment is None:
        return None
    return timezone.localtime(moment).replace(tzinfo=None)


def to_aware(moment: datetime | None) -> datetime | None:
    """A local date-time without a zone, as an aware date-time Django can store."""
    if moment is None:
        return None
    return timezone.make_aware(moment)


def local_now() -> datetime:
    """'Now' in the form dockops expects: local time without a zone."""
    return to_local_naive(timezone.now())


# ------------------------------------------------------------------- Queries

class TransportQuerySet(models.QuerySet):

    def relevant_to(self, start: date, end: date | None = None) -> "TransportQuerySet":
        """
        Every transport that may matter for the days start..end (end=None: no upper limit).

        A transport is loaded when its appointment is from LOOKBACK_DAYS before start
        up to end, when it actually arrived or departed in the period, or when it has no
        appointment. Loading too much is harmless: dockops decides what counts.
        """
        by_appointment = Q(planned_arrival__date__gte=start - timedelta(days=LOOKBACK_DAYS))
        arrived = Q(arrived_at__date__gte=start)
        departed = Q(departed_at__date__gte=start)
        if end is not None:
            by_appointment &= Q(planned_arrival__date__lte=end)
            arrived &= Q(arrived_at__date__lte=end)
            departed &= Q(departed_at__date__lte=end)
        no_appointment = Q(planned_arrival__isnull=True)
        return self.filter(by_appointment | arrived | departed | no_appointment)

    def to_domain(self) -> list[DomainTransport]:
        """The rows as dockops dataclasses."""
        return [transport.to_domain() for transport in self]

    def last_updated_at(self) -> datetime | None:
        """When the data last changed, in local time; None when there is no data."""
        return to_local_naive(self.aggregate(latest=Max("updated_at"))["latest"])


# ------------------------------------------------------------------- Model

class Transport(models.Model):
    """One vehicle visit. The fields mirror dockops.models.Transport (see DATA-MODEL)."""

    number = models.CharField(_("number"), max_length=32, unique=True)
    status = models.CharField(_("status"), max_length=16, choices=STATUS_CHOICES,
                              default=Status.SCHEDULED.value)
    cargo_type = models.CharField(_("cargo type"), max_length=8, choices=CARGO_TYPE_CHOICES,
                                  default=CargoType.DRY.value)
    bay = models.PositiveSmallIntegerField(_("bay"), null=True, blank=True)

    planned_arrival = models.DateTimeField(_("appointment"), null=True, blank=True, db_index=True)
    arrived_at = models.DateTimeField(_("arrived at"), null=True, blank=True, db_index=True)
    inspected_at = models.DateTimeField(_("inspected at"), null=True, blank=True)
    planned_loading_start = models.DateTimeField(_("planned loading start"), null=True, blank=True)
    loading_started_at = models.DateTimeField(_("loading started at"), null=True, blank=True)
    planned_loading_end = models.DateTimeField(_("planned loading end"), null=True, blank=True)
    loading_ended_at = models.DateTimeField(_("loading ended at"), null=True, blank=True)
    planned_departure = models.DateTimeField(_("planned departure"), null=True, blank=True)
    departed_at = models.DateTimeField(_("departed at"), null=True, blank=True, db_index=True)

    carrier = models.CharField(_("carrier"), max_length=100, blank=True)
    planner = models.CharField(_("planner"), max_length=100, blank=True)
    destination = models.CharField(_("destination"), max_length=100, blank=True)
    booking_ref = models.CharField(_("booking reference"), max_length=50, blank=True)
    seal_number = models.CharField(_("seal number"), max_length=50, blank=True)
    notes = models.TextField(_("notes"), blank=True)

    # Set on every save(); the board shows the newest one as "last update".
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    objects = TransportQuerySet.as_manager()

    class Meta:
        verbose_name = _("transport")
        verbose_name_plural = _("transports")
        ordering = ["planned_arrival", "number"]
        permissions = [("view_history", _("Can view the history page"))]

    def __str__(self) -> str:
        return self.number

    def to_domain(self) -> DomainTransport:
        """This row as the dataclass every dockops rule works with."""
        return DomainTransport(
            number=self.number,
            status=Status(self.status),
            cargo_type=CargoType(self.cargo_type),
            bay=self.bay,
            **{name: to_local_naive(getattr(self, name)) for name in TIME_FIELDS},
            **{name: getattr(self, name) for name in TEXT_FIELDS},
        )

    @classmethod
    def from_domain(cls, transport: DomainTransport) -> "Transport":
        """A new, unsaved row from a dockops dataclass (used by the seed and the simulator)."""
        row = cls()
        row.apply_domain(transport)
        return row

    def apply_domain(self, transport: DomainTransport) -> None:
        """Copy every field of a dockops dataclass onto this row (not saved yet)."""
        self.number = transport.number
        self.status = transport.status.value
        self.cargo_type = transport.cargo_type.value
        self.bay = transport.bay
        for name in TIME_FIELDS:
            setattr(self, name, to_aware(getattr(transport, name)))
        for name in TEXT_FIELDS:
            setattr(self, name, getattr(transport, name))
