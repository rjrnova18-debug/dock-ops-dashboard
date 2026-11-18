"""
The administration site for transports: browse, search and correct them, and advance the
demo simulation by hand.

The simulation is a button on the list page, not an admin "action": actions work on the
rows you select, and a simulation step moves the whole operation.
"""
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import path
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from board import simulator
from board.models import Transport, local_now


@admin.register(Transport)
class TransportAdmin(admin.ModelAdmin):
    change_list_template = "admin/board/transport/change_list.html"   # adds the simulation button
    list_display = ("number", "status", "cargo_type", "bay", "planned_arrival", "arrived_at", "departed_at", "carrier")
    list_filter = ("status", "cargo_type", "bay")
    search_fields = ("number", "carrier", "booking_ref", "seal_number")
    date_hierarchy = "planned_arrival"
    ordering = ("-planned_arrival",)
    readonly_fields = ("updated_at",)
    fieldsets = (
        (None, {"fields": ("number", "status", "cargo_type", "bay")}),
        (_("Plan"), {"fields": ("planned_arrival", "planned_loading_start", "planned_loading_end", "planned_departure")}),
        (_("Actual"), {"fields": ("arrived_at", "inspected_at", "loading_started_at", "loading_ended_at", "departed_at")}),
        (_("Details"), {"fields": ("carrier", "planner", "destination", "booking_ref", "seal_number", "notes", "updated_at")}),
    )

    def get_urls(self):
        simulate = path("simulate/", self.admin_site.admin_view(self.simulate_view), name="board_transport_simulate")
        return [simulate, *super().get_urls()]

    def simulate_view(self, request):
        """Advance the demo simulation one step. Only a POST from the list page's button does it."""
        if request.method == "POST":
            if not self.has_change_permission(request):
                raise PermissionDenied
            changes = simulator.run_step(local_now())
            message = ngettext("One step run: %(count)d transport changed.",
                               "One step run: %(count)d transports changed.", changes) % {"count": changes}
            self.message_user(request, message, messages.SUCCESS)
        return redirect("admin:board_transport_changelist")
