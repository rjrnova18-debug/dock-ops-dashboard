// Formatting for display, shared by every screen.
//
// The payloads carry no display text: dates arrive as ISO strings, durations as minutes
// and states as codes. This module turns them into words, always through Django's
// translation catalog (gettext, interpolate), loaded by the page from /jsi18n/.

/* global gettext, interpolate */

const LANG = document.documentElement.lang || "en";

// ------------------------------------------------------------------ Labels

export const STATUS = {
  scheduled: gettext("Scheduled"), waiting: gettext("Waiting"), inspected: gettext("Inspected"),
  loading: gettext("Loading"), loaded: gettext("Loaded"), dispatched: gettext("Dispatched"),
  in_transit: gettext("In transit"), delivered: gettext("Delivered"),
};
export const OUTCOME = {
  on_time: gettext("On time"), late: gettext("Late"), pending: gettext("Pending"), no_plan: gettext("No plan"),
};
export const CHECKPOINT = {
  arrival: gettext("Arrival"), inspection: gettext("Inspection"), loading_start: gettext("Loading start"),
  loading_end: gettext("Loading end"), departure: gettext("Departure"),
};
export const GROUP = {
  waiting: gettext("Yard"), earlier: gettext("Earlier"), today: gettext("Today"), tomorrow: gettext("Tomorrow"),
};
export const ALERT = {
  late_loading_start: gettext("Late loading start"), departure_due: gettext("Departure due"),
  loading_over_reference: gettext("Over reference"),
};
export const CARGO = { dry: gettext("Dry"), cold: gettext("Cold") };

const OUTCOME_ICON = { on_time: "✓", late: "!", pending: "◷", no_plan: "–" };

// ------------------------------------------------------------------ Text and numbers

/** Free text from the data is always escaped before it is put on the page. */
export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export const pad = (n) => String(n).padStart(2, "0");

/** Seconds as HH:MM:SS; hours can exceed 24. */
export function clock(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`;
}

/** Minutes as "45 min" or "2 h 05". */
export function duration(minutes) {
  if (minutes === null || minutes === undefined) return "–";
  const m = Math.round(Math.abs(minutes));
  if (m < 60) return interpolate(gettext("%(m)s min"), { m }, true);
  return interpolate(gettext("%(h)s h %(m)s"), { h: Math.floor(m / 60), m: pad(m % 60) }, true);
}

// ------------------------------------------------------------------ Dates (local time, no zone)

/** "2026-11-12T10:42:00" or "2026-11-12" as a Date built from its parts (never shifted by a zone). */
export function parseIso(iso) {
  if (!iso) return null;
  const [y, mo, d, h = 0, mi = 0, s = 0] = iso.split(/[-T:]/).map(Number);
  return new Date(y, mo - 1, d, h, mi, s);
}

export const isoDay = (iso) => (iso ? iso.slice(0, 10) : null);
export const hhmm = (iso) => (iso ? iso.slice(11, 16) : "–");
export const hhmmss = (iso) => (iso ? iso.slice(11, 19) : "--:--:--");

const weekdayName = (date) => new Intl.DateTimeFormat(LANG, { weekday: "short" }).format(date);
const monthName = (date) => new Intl.DateTimeFormat(LANG, { month: "short" }).format(date);

/** "Thu 12" */
export function dayLabel(iso) {
  const date = parseIso(iso);
  return `${weekdayName(date)} ${date.getDate()}`;
}

/** "Thu 12 Nov 2026" */
export function longDay(iso) {
  return new Intl.DateTimeFormat(LANG, { weekday: "short", day: "numeric", month: "short", year: "numeric" })
    .format(parseIso(iso));
}

/** "09 – 15 Nov", or "30 Nov – 06 Dec" across two months. */
export function weekRange(startIso, endIso) {
  const start = parseIso(startIso);
  const end = parseIso(endIso);
  const first = start.getMonth() === end.getMonth() ? pad(start.getDate()) : `${pad(start.getDate())} ${monthName(start)}`;
  return `${first} – ${pad(end.getDate())} ${monthName(end)}`;
}

/** A moment shown against today: "14:30" if it is today, "Tue 10 14:30" otherwise. */
export function moment(iso, todayIso) {
  if (!iso) return "–";
  return isoDay(iso) === todayIso ? hhmm(iso) : `${dayLabel(iso)} ${hhmm(iso)}`;
}

// ------------------------------------------------------------------ Small pieces of markup

/** An outcome is always a labelled badge; the colour lives in the badge. */
export const badge = (outcome) =>
  `<span class="badge ${esc(outcome)}">${OUTCOME_ICON[outcome] ?? ""} ${esc(OUTCOME[outcome] ?? outcome)}</span>`;

export const coldChip = (cargo) => (cargo === "cold" ? `<span class="chip-cold">◆ ${esc(gettext("Cold"))}</span>` : "");
