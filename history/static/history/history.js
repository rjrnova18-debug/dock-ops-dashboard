// The history page: the filters live in the page address, every change asks the server
// for the summary of the period, and the answer is drawn. No "apply" button.
//
// While a request runs the previous content stays, dimmed. A slow answer to an older
// request never overwrites a newer one: each request aborts the previous one and carries
// a number, and only the answer to the latest number is drawn.

/* global gettext, interpolate */
import { CARGO, duration, esc, pad, parseIso } from "../js/format.js";
import { createCharts, renderCharts } from "./history_charts.js";

const $ = (id) => document.getElementById(id);
const root = $("history");
const TODAY = root.dataset.today;                       // the server's day, not the device's
const WEEK_START = Number(root.dataset.weekStart);      // Python weekday: Monday = 0
const LANG = document.documentElement.lang || "en";
const SUGGESTED_GROUPING = { week: "day", month: "week", year: "month" };

// ------------------------------------------------------------------ Dates

const isoOf = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);

/** The first and last day of the chosen period, or null while it is incomplete. */
function periodOf(filters) {
  if (filters.period === "week" && filters.date) {
    const day = parseIso(filters.date);
    const weekday = (day.getDay() + 6) % 7;                         // JavaScript: Sunday = 0
    const start = addDays(day, -((weekday - WEEK_START + 7) % 7));
    return { start: isoOf(start), end: isoOf(addDays(start, 6)) };
  }
  if (filters.period === "month" && /^\d{4}-\d{2}$/.test(filters.date)) {
    const [y, m] = filters.date.split("-").map(Number);
    return { start: isoOf(new Date(y, m - 1, 1)), end: isoOf(new Date(y, m, 0)) };
  }
  if (filters.period === "year" && /^\d{4}$/.test(filters.date)) {
    return { start: `${filters.date}-01-01`, end: `${filters.date}-12-31` };
  }
  if (filters.period === "range" && filters.start && filters.end) {
    return { start: filters.start, end: filters.end };
  }
  return null;
}

// ------------------------------------------------------------------ Filters <-> address

const inputs = {
  period: $("periodKind"), week: $("weekDay"), month: $("month"), year: $("year"),
  start: $("rangeStart"), end: $("rangeEnd"), groupBy: $("groupBy"), cargo: $("cargo"),
};

function filtersFromAddress() {
  const q = new URLSearchParams(location.search);
  const period = ["week", "month", "year", "range"].includes(q.get("period")) ? q.get("period") : "month";
  const date = q.get("date") ?? { week: TODAY, month: TODAY.slice(0, 7), year: TODAY.slice(0, 4), range: "" }[period];
  return {
    period, date,
    start: q.get("start") ?? TODAY.slice(0, 8) + "01", end: q.get("end") ?? TODAY,
    groupBy: ["day", "week", "month"].includes(q.get("group_by")) ? q.get("group_by") : SUGGESTED_GROUPING[period] ?? "week",
    cargo: ["dry", "cold"].includes(q.get("cargo")) ? q.get("cargo") : "",
  };
}

function showFilters(filters) {
  inputs.period.value = filters.period;
  if (filters.period === "week") inputs.week.value = filters.date;
  if (filters.period === "month") inputs.month.value = filters.date;
  if (filters.period === "year") inputs.year.value = filters.date;
  inputs.start.value = filters.start;
  inputs.end.value = filters.end;
  inputs.groupBy.value = filters.groupBy;
  inputs.cargo.value = filters.cargo;
  document.querySelectorAll("[data-period]").forEach((label) => { label.hidden = label.dataset.period !== filters.period; });
}

function filtersFromInputs() {
  const period = inputs.period.value;
  const date = { week: inputs.week.value, month: inputs.month.value, year: inputs.year.value, range: "" }[period];
  return { period, date, start: inputs.start.value, end: inputs.end.value, groupBy: inputs.groupBy.value, cargo: inputs.cargo.value };
}

function writeAddress(filters) {
  const q = new URLSearchParams({ period: filters.period, group_by: filters.groupBy });
  if (filters.period === "range") { q.set("start", filters.start); q.set("end", filters.end); } else { q.set("date", filters.date); }
  if (filters.cargo) q.set("cargo", filters.cargo);
  window.history.replaceState(null, "", `?${q}`);            // bookmarkable, without a new history entry
}

/** The API's parameters for these filters. */
function apiQuery(filters, period) {
  const q = new URLSearchParams({ start: period.start, end: period.end, group_by: filters.groupBy });
  if (filters.cargo) q.set("cargo_type", filters.cargo);
  return q;
}

// ------------------------------------------------------------------ Loading

let latestRequest = 0;
let controller = null;

async function load() {
  const filters = filtersFromInputs();
  showFilters(filters);
  writeAddress(filters);
  const period = periodOf(filters);
  if (!period) return showMessage(gettext("The period is incomplete: choose its days."));
  if (period.end < period.start) return showMessage(gettext("The start of the period is after its end."));

  const query = apiQuery(filters, period);
  $("csvLink").href = `${root.dataset.csvUrl}?${query}`;
  $("excelLink").href = `${root.dataset.excelUrl}?${query}`;

  const request = ++latestRequest;
  controller?.abort();
  controller = new AbortController();
  $("content").classList.add("loading");
  try {
    const response = await fetch(`${root.dataset.url}?${query}`, { signal: controller.signal, headers: { Accept: "application/json" } });
    if (request !== latestRequest) return;
    if (response.status === 401) {                              // the session expired: sign in and come back here
      location.href = `${root.dataset.loginUrl}?next=${encodeURIComponent(location.pathname + location.search)}`;
      return;
    }
    const body = await response.json();
    if (!response.ok) return showMessage(body.error ?? gettext("The server could not answer."));
    render(body, filters, period);
  } catch (error) {
    if (error.name === "AbortError") return;
    showMessage(gettext("The server cannot be reached. Check the connection and try again."));
  } finally {
    if (request === latestRequest) $("content").classList.remove("loading");
  }
}

function showMessage(text, kind = "") {
  $("message").innerHTML = text ? `<p class="notice ${kind}" role="alert">${esc(text)}</p>` : "";
}

// ------------------------------------------------------------------ Drawing

function render(summary, filters, period) {
  const visible = summary.cargo_type ? [summary.cargo_type] : ["dry", "cold"];
  $("summaryLine").textContent = describe(filters, period, summary);
  const t = summary.totals;
  const empty = !summary.series.length && !t.appointments && !t.dispatched && !t.workload;
  showMessage(empty ? gettext("Nothing was recorded in this period. The history only covers what the system has recorded.") : "", "info");
  renderTiles(summary, visible);
  renderCharts(summary, visible);
}

/** "November 2026 · all cargo types · grouped by week" */
function describe(filters, period, summary) {
  const day = (iso) => new Intl.DateTimeFormat(LANG, { day: "numeric", month: "short", year: "numeric" }).format(parseIso(iso));
  const when = {
    week: () => interpolate(gettext("Week of %(start)s to %(end)s"), { start: day(period.start), end: day(period.end) }, true),
    month: () => new Intl.DateTimeFormat(LANG, { month: "long", year: "numeric" }).format(parseIso(period.start)),
    year: () => period.start.slice(0, 4),
    range: () => interpolate(gettext("From %(start)s to %(end)s"), { start: day(period.start), end: day(period.end) }, true),
  }[filters.period]();
  const cargo = { "": gettext("all cargo types"), dry: gettext("dry cargo only"), cold: gettext("cold cargo only") }[filters.cargo];
  const grouping = { day: gettext("grouped by day"), week: gettext("grouped by week"), month: gettext("grouped by month") }[summary.group_by];
  return `${when} · ${cargo} · ${grouping}`;
}

function renderTiles(summary, visible) {
  const pct = (part, whole) => (whole ? `${Math.round((part / whole) * 100)}%` : "–");
  const tiles = [
    { label: gettext("Appointments"), show: (n) => String(n.appointments) },
    { label: gettext("Dispatched"),
      show: (n) => interpolate(gettext("%(dispatched)s of %(workload)s · %(percent)s"),
        { dispatched: n.dispatched, workload: n.workload, percent: pct(n.dispatched, n.workload) }, true),
      help: gettext("Of the workload: the appointments of the period, the carryovers it started with, and everything dispatched during it.") },
    { label: gettext("Average loading time"), show: (n) => duration(n.loading_average_minutes) },
    { label: gettext("Average cycle time"), show: (n) => duration(n.cycle_average_minutes) },
    { label: gettext("Adherence"), show: (n) => (n.adherence_percent === null ? "–" : `${n.adherence_percent}%`) },
  ];
  $("tiles").innerHTML = tiles.map((tile) => `
    <article class="panel cut tile"><div class="in cut"><div class="pb">
      <span class="label">${esc(tile.label)}${tile.help ? `<details><summary>${esc(gettext("What is the workload?"))}</summary>${esc(tile.help)}</details>` : ""}</span>
      <span class="value">${esc(tile.show(summary.totals))}</span>
      <span class="split">${visible.map((cargo) => `<span>${esc(CARGO[cargo])} <b>${esc(tile.show(summary.by_cargo_type[cargo]))}</b></span>`).join("")}</span>
    </div></div></article>`).join("");
}

// ------------------------------------------------------------------ Events

function onPeriodKindChange() {
  const period = inputs.period.value;
  const fallback = { week: TODAY, month: TODAY.slice(0, 7), year: TODAY.slice(0, 4) }[period];
  if (period === "week" && !inputs.week.value) inputs.week.value = fallback;
  if (period === "month" && !inputs.month.value) inputs.month.value = fallback;
  if (period === "year" && !inputs.year.value) inputs.year.value = fallback;
  if (SUGGESTED_GROUPING[period]) inputs.groupBy.value = SUGGESTED_GROUPING[period];   // a suggestion; it can be changed
  load();
}

createCharts();
showFilters(filtersFromAddress());
inputs.period.addEventListener("change", onPeriodKindChange);
for (const input of [inputs.week, inputs.month, inputs.year, inputs.start, inputs.end, inputs.groupBy, inputs.cargo]) {
  input.addEventListener("change", load);
}
$("printButton").addEventListener("click", () => window.print());
document.querySelectorAll(".chart-card").forEach((card) => {
  for (const [selector, cls] of [["[data-show-table]", "show-table"], ["[data-widen]", "wide"]]) {
    const button = card.querySelector(selector);
    button.addEventListener("click", () => {
      const on = card.classList.toggle(cls);
      button.setAttribute("aria-pressed", String(on));
    });
  }
});
load();
