// The history's tables: the slowest and fastest loadings, the unclosed transports, and the
// transport detail that opens from a loading row (a <dialog>: closes with its control,
// Escape or a click outside).

/* global gettext, interpolate */
import { CARGO, STATUS, coldChip, dayLabel, duration, esc, isoDay, moment, pad, planVersusActual } from "../js/format.js";

const $ = (id) => document.getElementById(id);
const dialog = $("overlay");
let loadings = new Map();          // number -> loading row, for the detail
let today = null;

const table = (head, rows) =>
  `<table class="t"><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
const day = (iso) => (iso ? dayLabel(iso) : "–");

// ------------------------------------------------------------------ Slowest and fastest loadings (H6)

export function renderExtremes(summary) {
  today = isoDay(summary.generated_at);
  loadings = new Map([...summary.slowest_loadings, ...summary.fastest_loadings].map((row) => [row.number, row]));
  $("slowest").innerHTML = loadingTable(summary.slowest_loadings);
  $("fastest").innerHTML = loadingTable(summary.fastest_loadings);
}

function loadingTable(rows) {
  if (!rows.length) return `<p class="empty-note">${esc(gettext("No loading ended in this period."))}</p>`;
  const head = [gettext("Transport"), gettext("Cargo type"), gettext("Appointment day"), gettext("Bay"), gettext("Carrier"),
    gettext("Loading time"), gettext("Cycle time")];
  return table(head, rows.map((row) => `
    <tr class="row" tabindex="0" data-loading="${esc(row.number)}"
        aria-label="${esc(interpolate(gettext("%(number)s. Open detail."), { number: row.number }, true))}">
      <td><b>${esc(row.number)}</b></td><td>${esc(CARGO[row.cargo_type])}</td><td>${esc(day(row.appointment_day))}</td>
      <td>${row.bay === null ? "–" : pad(row.bay)}</td><td>${esc(row.carrier)}</td>
      <td><b>${esc(duration(row.loading_minutes))}</b></td><td>${esc(duration(row.cycle_minutes))}</td></tr>`));
}

// ------------------------------------------------------------------ Unclosed transports (H7)

export function renderUnclosed(unclosed) {
  $("unclosedCount").textContent = unclosed.total;
  if (!unclosed.total) {
    $("unclosed").innerHTML = `<p class="empty-note">${esc(gettext("None in this period."))}</p>`;
    return;
  }
  const head = [gettext("Transport"), gettext("Appointment day"), gettext("Status"), gettext("Cargo type"), gettext("Carrier"), gettext("Notes")];
  const rows = unclosed.rows.map((row) => `<tr><td><b>${esc(row.number)}</b></td><td>${esc(day(row.appointment_day))}</td>
    <td>${esc(STATUS[row.status])}</td><td>${esc(CARGO[row.cargo_type])}</td><td>${esc(row.carrier)}</td><td>${esc(row.notes)}</td></tr>`);
  const more = unclosed.total > unclosed.rows.length
    ? `<p class="sub">${esc(interpolate(gettext("Showing the oldest %(shown)s of %(total)s."), { shown: unclosed.rows.length, total: unclosed.total }, true))}</p>`
    : "";
  $("unclosed").innerHTML = table(head, rows) + more;
}

// ------------------------------------------------------------------ Transport detail

export function setupDetail() {
  const open = (target) => {
    const row = target.closest?.("[data-loading]");
    if (row) openDetail(row.dataset.loading);
  };
  document.addEventListener("click", (event) => open(event.target));
  document.addEventListener("keydown", (event) => {
    if ((event.key === "Enter" || event.key === " ") && event.target.matches?.("[data-loading]")) {
      event.preventDefault();
      open(event.target);
    }
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog || event.target.closest(".x")) dialog.close();
  });
}

function openDetail(number) {
  const row = loadings.get(number);
  if (!row) return;
  const field = (label, value) => `<div><div class="k">${esc(label)}</div><div class="v">${esc(value || "–")}</div></div>`;
  const d = row.detail;
  dialog.innerHTML = `
    <div class="dh"><h3 id="overlayTitle">${esc(row.number)}</h3>${coldChip(row.cargo_type)}
      <button class="x" type="button" aria-label="${esc(gettext("Close"))}">✕</button></div>
    <div class="dbody">
      <div class="dsec"><h4>${esc(gettext("Summary"))}</h4><div class="dgrid">
        ${field(gettext("Cargo type"), CARGO[row.cargo_type])}${field(gettext("Appointment day"), day(row.appointment_day))}
        ${field(gettext("Bay"), row.bay === null ? "" : pad(row.bay))}${field(gettext("Carrier"), row.carrier)}
        ${field(gettext("Loading start"), moment(row.loading_started_at, today))}${field(gettext("Loading end"), moment(row.loading_ended_at, today))}
        ${field(gettext("Loading time"), duration(row.loading_minutes))}${field(gettext("Cycle time"), duration(row.cycle_minutes))}
      </div></div>
      <div class="dsec"><h4>${esc(gettext("Plan versus actual"))}</h4>${planVersusActual(d.checkpoints, today)}</div>
      <div class="dsec"><h4>${esc(gettext("Transport data"))}</h4><div class="dgrid">
        ${field(gettext("Planner"), d.planner)}${field(gettext("Destination"), d.destination)}
        ${field(gettext("Booking reference"), d.booking_ref)}${field(gettext("Seal number"), d.seal_number)}
      </div></div>
    </div>`;
  dialog.showModal();
}
