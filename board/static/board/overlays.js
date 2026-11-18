// The board's overlays: an enlarged chart with its source rows, the completed list and
// the transport detail.
//
// One overlay at a time, in a single <dialog>. It closes with its close control, the
// Escape key or a click outside, and it follows every new payload while it is open.
// board.js passes in what it needs (setupOverlays), so this module never imports it.

/* global gettext, interpolate */
import {
  CARGO, CHECKPOINT, STATUS, badge, coldChip, dayLabel, duration, esc, hhmm, isoDay, moment, pad, planVersusActual,
} from "../js/format.js";
import { STATUS_COLORS, createTrendChart, renderGauges, renderPipeline, updateTrendChart } from "./charts.js";

const dialog = document.getElementById("overlay");
let deps = null;               // { getPayload, timerBlock } from board.js
let view = null;               // what is open: { kind, chart?, number?, source?, from? }
let bigChart = null;           // the Chart.js instance of an enlarged trend
let lastDetail = null;         // the last transport shown; it stays if the transport leaves the payload
const completed = { search: "", sort: "bay", descending: false };   // survives refreshes, reset on close

const CHART_TITLE = {
  status: gettext("Status"), loading: gettext("Loading time"), cycle: gettext("Cycle time"), adherence: gettext("Adherence"),
};

// ------------------------------------------------------------------ Opening and closing

export function setupOverlays(dependencies) {
  deps = dependencies;
  document.addEventListener("click", (event) => activate(event.target));
  document.addEventListener("keydown", (event) => {
    if ((event.key === "Enter" || event.key === " ") && event.target.matches?.("[data-number][tabindex]")) {
      event.preventDefault();
      activate(event.target);
    }
  });
  document.getElementById("weekButton").addEventListener("click", () => open({ kind: "completed" }));
  document.querySelectorAll("[data-expand]").forEach((button) =>
    button.addEventListener("click", () => open({ kind: "chart", chart: button.dataset.expand })));
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();                 // a click on the backdrop
    if (event.target.closest(".x")) dialog.close();
    if (event.target.closest(".back")) open({ kind: "completed" });
  });
  dialog.addEventListener("input", (event) => {
    if (event.target.id === "completedSearch") { completed.search = event.target.value; renderCompletedRows(); }
  });
  dialog.addEventListener("change", (event) => {
    if (event.target.id === "completedSort") { completed.sort = event.target.value; renderCompletedRows(); }
  });
  dialog.addEventListener("close", () => {
    view = null; lastDetail = null; dialog.dataset.view = "";
    Object.assign(completed, { search: "", sort: "bay", descending: false });
    bigChart?.destroy(); bigChart = null;
  });
}

/** Called by board.js with every new payload. */
export function refreshOverlay() {
  if (dialog.open) render();
}

function activate(target) {
  const row = target.closest?.("[data-number]");
  if (!row) return;
  open({ kind: "detail", number: row.dataset.number, source: row.dataset.source,
         from: view?.kind === "completed" ? "completed" : null });
}

function open(next) {
  view = next;
  render();
  if (!dialog.open) dialog.showModal();
}

function render() {
  const payload = deps.getPayload();
  if (!payload || !view) return;
  const key = `${view.kind}:${view.chart ?? view.number ?? ""}`;
  const mount = dialog.dataset.view !== key;        // a new view is built; the same view is only refilled
  if (mount) {
    bigChart?.destroy(); bigChart = null;
    dialog.dataset.view = key;
  }
  if (view.kind === "chart") renderChart(payload, mount);
  if (view.kind === "completed") renderCompleted(payload, mount);
  if (view.kind === "detail") renderDetail(payload);
}

function header(title, { sub = "", back = false } = {}) {
  return `<div class="dh">
    ${back ? `<button class="back" type="button">◂ ${esc(gettext("Back to list"))}</button>` : ""}
    <h3 id="overlayTitle">${title}</h3>${sub}
    <button class="x" type="button" aria-label="${esc(gettext("Close"))}">✕</button></div>`;
}

const table = (columns, body, id = "") =>
  `<table class="t"><thead><tr>${columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody ${id ? `id="${id}"` : ""}>${body}</tbody></table>`;

/** Working time, and clock time too when the two differ. */
function workingAndClock(measure) {
  if (!measure) return "–";
  const working = measure.working_minutes ?? measure;
  const clockMinutes = measure.clock_minutes;
  const extra = clockMinutes !== undefined && Math.round(clockMinutes) !== Math.round(working)
    ? `<span class="cell-sub">${esc(interpolate(gettext("%(time)s clock time"), { time: duration(clockMinutes) }, true))}</span>` : "";
  return `${esc(duration(working))}${extra}`;
}

// ------------------------------------------------------------------ Enlarged chart

function renderChart(payload, mount) {
  const today = isoDay(payload.generated_at);
  const kind = view.chart;
  if (mount) {
    const visual = kind === "loading" || kind === "cycle"
      ? `<div class="chartbox"><canvas id="bigChart"></canvas></div>`
      : `<div id="bigVisual" class="${kind === "adherence" ? "gauges" : ""}"></div>`;
    dialog.innerHTML = `${header(esc(CHART_TITLE[kind]))}<div class="dbody">${visual}<div id="chartRows"></div></div>`;
    if (kind === "loading" || kind === "cycle") bigChart = createTrendChart(document.getElementById("bigChart"));
  }
  const rows = document.getElementById("chartRows");
  if (kind === "status") {
    renderPipeline(document.getElementById("bigVisual"), payload.status_chart);
    rows.innerHTML = table(
      [gettext("Bay"), gettext("Transport"), gettext("Appointment day"), gettext("Status"), gettext("Carrier"), gettext("Booking reference")],
      payload.status_chart.rows.map((r) => `<tr class="row" tabindex="0" data-number="${esc(r.number)}" data-source="board">
        <td>${r.bay ?? "–"}</td><td><b>${esc(r.number)}</b></td><td>${r.appointment_day ? esc(dayLabel(r.appointment_day)) : "–"}</td>
        <td>${esc(STATUS[r.status])}</td><td>${esc(r.carrier)}</td><td>${esc(r.booking_ref)}</td></tr>`).join(""));
  }
  if (kind === "loading" || kind === "cycle") {
    const chart = payload[`${kind}_chart`];
    updateTrendChart(bigChart, chart);
    const [startLabel, endLabel] = kind === "loading"
      ? [gettext("Loading start"), gettext("Loading end")] : [gettext("Actual arrival"), gettext("Actual departure")];
    rows.innerHTML = table(
      [gettext("Day"), gettext("Bay"), gettext("Transport"), gettext("Cargo type"), startLabel, endLabel, gettext("Duration")],
      chart.rows.map((r) => `<tr><td>${esc(dayLabel(r.day))}</td><td>${r.bay ?? "–"}</td><td><b>${esc(r.number)}</b></td>
        <td>${esc(CARGO[r.cargo_type])}</td><td>${esc(moment(r.start, today))}</td><td>${esc(moment(r.end, today))}</td>
        <td>${workingAndClock(r)}</td></tr>`).join(""));
  }
  if (kind === "adherence") {
    const chart = payload.adherence_chart;
    renderGauges(document.getElementById("bigVisual"), chart);
    rows.innerHTML = table(
      [gettext("Bay"), gettext("Transport"), gettext("Appointment day"), gettext("Cargo type"), ...chart.checkpoints.map((c) => CHECKPOINT[c])],
      chart.rows.map((r) => `<tr class="row" tabindex="0" data-number="${esc(r.number)}" data-source="board">
        <td>${r.bay ?? "–"}</td><td><b>${esc(r.number)}</b></td><td>${r.appointment_day ? esc(dayLabel(r.appointment_day)) : "–"}</td>
        <td>${esc(CARGO[r.cargo_type])}</td>
        ${r.checkpoints.map((c) => `<td>${esc(hhmm(c.expected))} → ${esc(hhmm(c.actual))}<br>${badge(c.outcome)}</td>`).join("")}</tr>`).join(""));
  }
}

// ------------------------------------------------------------------ Completed list

const SORT_KEYS = {
  bay: (r) => r.bay,
  arrival: (r) => r.arrived_at,
  departure: (r) => r.departed_at,
  loading: (r) => r.loading?.working_minutes ?? null,
};

function renderCompleted(payload, mount) {
  if (mount) {
    const week = payload.week;
    const sub = `<span class="dh-sub">${esc(interpolate(gettext("%(dispatched)s of %(workload)s dispatched"), week, true))}</span>`;
    const option = (value, label) => `<option value="${value}" ${completed.sort === value ? "selected" : ""}>${esc(label)}</option>`;
    dialog.innerHTML = `${header(esc(gettext("Completed this week")), { sub })}
      <div class="dbody">
        <div class="tools">
          <input id="completedSearch" type="search" value="${esc(completed.search)}" placeholder="${esc(gettext("Search transport number…"))}"
                 aria-label="${esc(gettext("Search transport number"))}">
          <label class="sub">${esc(gettext("Sort by"))}
            <select id="completedSort">${option("bay", gettext("Bay"))}${option("arrival", gettext("Actual arrival"))}
              ${option("departure", gettext("Actual departure"))}${option("loading", gettext("Loading time"))}</select></label>
          <button class="expand" id="completedOrder" type="button"></button>
        </div>
        <div id="completedRows"></div>
      </div>`;
    document.getElementById("completedOrder").addEventListener("click", () => {
      completed.descending = !completed.descending;
      renderCompletedRows();
    });
  }
  renderCompletedRows();
}

function renderCompletedRows() {
  const payload = deps.getPayload();
  const today = isoDay(payload.generated_at);
  const order = document.getElementById("completedOrder");
  order.textContent = completed.descending ? `▼ ${gettext("Descending")}` : `▲ ${gettext("Ascending")}`;

  const search = completed.search.trim().toLowerCase();
  const key = SORT_KEYS[completed.sort];
  const rows = payload.week.completed
    .filter((r) => r.number.toLowerCase().includes(search))
    .sort((a, b) => {
      const [x, y] = [key(a), key(b)];
      if (x === null || x === undefined) return 1;          // rows without the value always go last
      if (y === null || y === undefined) return -1;
      const result = x < y ? -1 : x > y ? 1 : 0;
      return completed.descending ? -result : result;
    });

  document.getElementById("completedRows").innerHTML = rows.length ? table(
    [gettext("Bay"), gettext("Transport"), gettext("Status"), gettext("Actual arrival"), gettext("Actual departure"),
     gettext("Loading time"), gettext("Carrier"), gettext("Notes")],
    rows.map((r) => `<tr class="row" tabindex="0" data-number="${esc(r.number)}" data-source="completed">
      <td>${r.bay === null ? "–" : pad(r.bay)}</td><td><b>${esc(r.number)}</b> ${coldChip(r.cargo_type)}</td>
      <td>${esc(STATUS[r.status])}</td><td>${esc(moment(r.arrived_at, today))}</td><td>${esc(moment(r.departed_at, today))}</td>
      <td>${workingAndClock(r.loading)}</td><td>${esc(r.carrier)}</td><td>${esc(r.notes)}</td></tr>`).join(""))
    : `<p class="empty-note">${esc(gettext("No transport matches the search."))}</p>`;
}

// ------------------------------------------------------------------ Transport detail

function findTransport(payload, number, source) {
  if (source === "completed") return payload.week.completed.find((r) => r.number === number);
  for (const bay of payload.bays) {
    const row = bay.transports.find((r) => r.number === number);
    if (row) return row;
  }
  return payload.incoming.find((r) => r.number === number)
    ?? payload.week.completed.find((r) => r.number === number);    // e.g. opened from a chart table
}

function renderDetail(payload) {
  const found = findTransport(payload, view.number, view.source);
  if (found) lastDetail = found;
  const row = lastDetail;
  if (!row) {
    dialog.innerHTML = `${header(esc(view.number))}<div class="dbody"><p class="empty-note">${esc(gettext("This transport is not on the board any more."))}</p></div>`;
    return;
  }
  const today = isoDay(payload.generated_at);
  const fromCompleted = !("timer" in row || "group" in row);     // completed rows carry neither
  const field = (label, value) => `<div><div class="k">${esc(label)}</div><div class="v">${value}</div></div>`;
  const arrival = row.detail.checkpoints[0];
  const appointmentDay = isoDay(arrival.expected);

  const summary = fromCompleted
    ? [
      field(gettext("Status"), esc(STATUS[row.status])),
      field(gettext("Bay"), row.bay === null ? "–" : pad(row.bay)),
      field(gettext("Actual arrival"), esc(moment(row.arrived_at, today))),
      field(gettext("Actual departure"), esc(moment(row.departed_at, today))),
      field(gettext("Loading time"), workingAndClock(row.loading)),
      field(gettext("Cycle time"), workingAndClock(row.cycle)),
      field(gettext("Notes"), esc(row.notes || "–")),
    ]
    : [
      field(gettext("Status"), `<span class="lamp" style="display:inline-block;margin-right:6px;--l:${STATUS_COLORS[row.status].bg}"></span>${esc(STATUS[row.status])}`),
      field(gettext("Bay"), row.bay === null ? esc(gettext("not assigned")) : pad(row.bay)),
      field(gettext("Departs by"), `${esc(moment(row.planned_departure, today))} ${row.departure_overdue ? `<span class="badge late">! ${esc(gettext("Overdue"))}</span>` : ""}`),
      field(gettext("Notes"), esc(row.notes || "–")),
    ];
  const timer = !fromCompleted && row.timer ? `<div class="dsec"><h4>${esc(gettext("Loading timer"))}</h4>${deps.timerBlock(row)}</div>` : "";

  const d = row.detail;
  const data = [
    field(gettext("Carrier"), esc(d.carrier || "–")), field(gettext("Planner"), esc(d.planner || "–")),
    field(gettext("Destination"), esc(d.destination || "–")), field(gettext("Booking reference"), esc(d.booking_ref || "–")),
    field(gettext("Seal number"), esc(d.seal_number || "–")), field(gettext("Cargo type"), esc(CARGO[row.cargo_type])),
    field(gettext("Appointment day"), appointmentDay ? esc(dayLabel(appointmentDay)) : "–"),
  ];

  const carry = row.is_carryover ? `<span class="chip-carry">${esc(gettext("Carryover"))}</span>` : "";
  dialog.innerHTML = `${header(esc(row.number), { sub: coldChip(row.cargo_type) + carry, back: view.from === "completed" })}
    <div class="dbody">
      <div class="dsec"><h4>${esc(gettext("Summary"))}</h4><div class="dgrid">${summary.join("")}</div></div>
      ${timer}
      <div class="dsec"><h4>${esc(gettext("Plan versus actual"))}</h4>
        ${planVersusActual(row.detail.checkpoints, today)}</div>
      <div class="dsec"><h4>${esc(gettext("Transport data"))}</h4><div class="dgrid">${data.join("")}</div></div>
    </div>`;
}
