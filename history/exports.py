"""
The history downloads (HISTORY.md, "Downloads"): the fact table as CSV, and a four-sheet
Excel workbook. dockops gives plain values; this module only decides how files look.

The fact table's column names are a contract with whoever reads the files: they come
from dockops.history.FACT_COLUMNS and are never translated, renamed or reordered.
"""
import csv
from datetime import date, datetime
from io import BytesIO

from django.http import HttpResponse
from django.utils.translation import gettext as _
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from dockops.history import FACT_COLUMNS
from dockops.models import CargoType

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
INDICATORS = ("appointments", "dispatched", "loading_average_minutes", "loading_count",
              "cycle_average_minutes", "cycle_count", "adherence_percent")
BOLD = Font(bold=True)


def file_name(start: date, end: date, cargo_type: CargoType | None, extension: str) -> str:
    """dock-ops-history_2026-11-01_2026-11-30[_cold].csv"""
    cargo = f"_{cargo_type.value}" if cargo_type else ""
    return f"dock-ops-history_{start.isoformat()}_{end.isoformat()}{cargo}.{extension}"


def _attachment(response: HttpResponse, name: str) -> HttpResponse:
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


# ------------------------------------------------------------------- CSV

def csv_response(rows: list[dict], name: str) -> HttpResponse:
    """The fact table, UTF-8 with a byte-order mark so spreadsheets read accents correctly."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow(FACT_COLUMNS)
    for row in rows:
        writer.writerow([_csv_value(row[column]) for column in FACT_COLUMNS])
    return _attachment(response, name)


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    return value


# ------------------------------------------------------------------- Excel

def excel_response(summary: dict, daily_series: list[dict] | None, rows: list[dict], name: str) -> HttpResponse:
    """
    Summary · By <grouping> · By day (left out when the grouping is already by day) · Transports.
    """
    workbook = Workbook()
    _summary_sheet(workbook.active, summary)
    _series_sheet(workbook.create_sheet(_by_grouping_title(summary["group_by"])), summary["series"], summary["group_by"])
    if daily_series is not None:
        _series_sheet(workbook.create_sheet(_("By day")), daily_series, "day")
    _transports_sheet(workbook.create_sheet(_("Transports")), rows)
    buffer = BytesIO()
    workbook.save(buffer)
    return _attachment(HttpResponse(buffer.getvalue(), content_type=XLSX_TYPE), name)


def _by_grouping_title(group_by: str) -> str:
    return {"day": _("By day"), "week": _("By week"), "month": _("By month")}[group_by]


def _header(sheet: Worksheet, values: list) -> None:
    sheet.append(values)
    for cell in sheet[sheet.max_row]:
        cell.font = BOLD


def _summary_sheet(sheet: Worksheet, summary: dict) -> None:
    sheet.title = _("Summary")
    cargo = summary["cargo_type"]
    for label, value in [
        (_("Period"), f"{summary['period_start']} – {summary['period_end']}"),
        (_("Cargo type"), _("All") if cargo is None else {"dry": _("Dry"), "cold": _("Cold")}[cargo]),
        (_("Grouped by"), summary["group_by"]),
        (_("Generated at"), summary["generated_at"].replace("T", " ")),
    ]:
        sheet.append([label, value])
        sheet.cell(sheet.max_row, 1).font = BOLD

    sheet.append([])
    _header(sheet, [_("Indicator"), _("All"), _("Dry"), _("Cold")])
    by_cargo = summary["by_cargo_type"]
    for key in (*INDICATORS, "workload"):
        sheet.append([key, summary["totals"][key], by_cargo["dry"][key], by_cargo["cold"][key]])

    sheet.append([])
    _header(sheet, [_("Checkpoint"), _("Adherence %"), _("On time"), _("Late"), _("No plan"), _("Pending"),
                    _("Dry %"), _("Cold %")])
    for item in summary["checkpoints"]:
        sheet.append([item["checkpoint"], item["percent"], item["on_time"], item["late"], item["no_plan"],
                      item["pending"], item["by_cargo_type"]["dry"], item["by_cargo_type"]["cold"]])
    sheet.column_dimensions["A"].width = 26
    for column in "BCDEFGH":
        sheet.column_dimensions[column].width = 14


def _series_sheet(sheet: Worksheet, series: list[dict], group_by: str) -> None:
    """One row per bucket: the indicators for all transports, then for each cargo type."""
    cargo_columns = [f"{name}_{cargo.value}" for cargo in CargoType for name in INDICATORS]
    _header(sheet, [group_by, *INDICATORS, *cargo_columns])
    for bucket in series:
        per_cargo = [bucket["by_cargo_type"][cargo.value][name] for cargo in CargoType for name in INDICATORS]
        sheet.append([bucket["key"], *(bucket[name] for name in INDICATORS), *per_cargo])
    sheet.freeze_panes = "B2"


def _transports_sheet(sheet: Worksheet, rows: list[dict]) -> None:
    _header(sheet, list(FACT_COLUMNS))
    for row in rows:
        sheet.append([row[column] for column in FACT_COLUMNS])
    for column in sheet.iter_cols(min_row=2):
        for cell in column:
            if isinstance(cell.value, datetime):
                cell.number_format = "yyyy-mm-dd hh:mm"
            elif isinstance(cell.value, date):
                cell.number_format = "yyyy-mm-dd"
    sheet.auto_filter.ref = sheet.dimensions          # filters on the header row
    sheet.freeze_panes = "B2"
