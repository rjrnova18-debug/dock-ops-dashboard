"""The history downloads: CSV (also with an export key) and the four-sheet Excel workbook."""
import csv
from datetime import datetime
from io import BytesIO, StringIO

import pytest
from django.test import override_settings
from django.urls import reverse
from openpyxl import load_workbook

from dockops.history import FACT_COLUMNS

pytestmark = pytest.mark.django_db

CSV, EXCEL = reverse("history:csv"), reverse("history:excel")
NOVEMBER = {"start": "2026-11-01", "end": "2026-11-30"}


def csv_rows(response) -> list[list[str]]:
    text = response.content.decode("utf-8")
    assert text.startswith("﻿")                       # byte-order mark for spreadsheets
    return list(csv.reader(StringIO(text.lstrip("﻿"))))


# ------------------------------------------------------------------- CSV

def test_the_csv_needs_access(client, outsider):
    assert client.get(CSV, NOVEMBER).status_code == 401
    client.force_login(outsider)
    assert client.get(CSV, NOVEMBER).status_code == 403


def test_the_csv_is_the_fact_table(client, viewer, seeded):
    client.force_login(viewer)

    response = client.get(CSV, {**NOVEMBER, "cargo_type": "cold"})
    rows = csv_rows(response)

    assert response["Content-Type"].startswith("text/csv")
    assert 'filename="dock-ops-history_2026-11-01_2026-11-30_cold.csv"' in response["Content-Disposition"]
    assert rows[0] == list(FACT_COLUMNS)
    assert len(rows) > 1
    assert {row[FACT_COLUMNS.index("cargo_type")] for row in rows[1:]} == {"cold"}


def test_the_grouping_does_not_change_the_csv(client, viewer, seeded):
    client.force_login(viewer)

    by_day = client.get(CSV, {**NOVEMBER, "group_by": "day"}).content
    by_month = client.get(CSV, {**NOVEMBER, "group_by": "month"}).content

    assert by_day == by_month


@override_settings(HISTORY_EXPORT_KEY="a-long-export-key")
def test_a_tool_can_download_the_csv_with_the_key(client, seeded):
    assert client.get(CSV, NOVEMBER, HTTP_X_EXPORT_KEY="a-long-export-key").status_code == 200
    assert client.get(CSV, NOVEMBER, HTTP_X_EXPORT_KEY="a-wrong-key").status_code == 401


@override_settings(HISTORY_EXPORT_KEY="")
def test_an_empty_key_setting_disables_the_route(client):
    assert client.get(CSV, NOVEMBER, HTTP_X_EXPORT_KEY="").status_code == 401


@override_settings(HISTORY_EXPORT_KEY="a-long-export-key")
def test_the_key_does_not_open_the_excel_download(client):
    assert client.get(EXCEL, NOVEMBER, HTTP_X_EXPORT_KEY="a-long-export-key").status_code == 401


# ------------------------------------------------------------------- Excel

def open_workbook(response):
    return load_workbook(BytesIO(response.content))


def test_the_workbook_has_four_sheets(client, viewer, seeded):
    client.force_login(viewer)

    response = client.get(EXCEL, NOVEMBER)
    workbook = open_workbook(response)

    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    assert workbook.sheetnames == ["Summary", "By week", "By day", "Transports"]


def test_grouping_by_day_leaves_out_the_extra_daily_sheet(client, viewer, seeded):
    client.force_login(viewer)

    workbook = open_workbook(client.get(EXCEL, {**NOVEMBER, "group_by": "day"}))

    assert workbook.sheetnames == ["Summary", "By day", "Transports"]


def test_the_transports_sheet_has_filters_and_real_dates(client, viewer, seeded):
    client.force_login(viewer)

    sheet = open_workbook(client.get(EXCEL, NOVEMBER))["Transports"]
    header = [cell.value for cell in sheet[1]]
    arrived = sheet.cell(row=2, column=header.index("planned_arrival") + 1).value

    assert header == list(FACT_COLUMNS)
    assert sheet.auto_filter.ref
    assert isinstance(arrived, datetime)


def test_the_summary_lists_the_indicators_and_the_checkpoints(client, viewer, seeded):
    client.force_login(viewer)

    sheet = open_workbook(client.get(EXCEL, NOVEMBER))["Summary"]
    first_column = [row[0].value for row in sheet.iter_rows()]

    assert "workload" in first_column and "adherence_percent" in first_column
    assert {"arrival", "inspection", "loading_start", "loading_end", "departure"} <= set(first_column)
