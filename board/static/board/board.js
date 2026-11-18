// The live board: asks the server for the payload on a fixed interval and paints it.
//
// The server does every calculation (working time, timer levels, alerts). Between two
// answers the screen only adds the seconds that pass to the running timers and to the
// clock, measured from the moment the answer arrived, never from the device's clock setting.

/* global gettext, ngettext, interpolate */
import {
  ALERT, GROUP, STATUS, badge, clock, coldChip, dayLabel, duration, esc, hhmm, hhmmss, longDay, moment, pad, weekRange,
} from "../js/format.js";
import { STATUS_COLORS, createTrendChart, renderGauges, renderPipeline, updateTrendChart } from "./charts.js";
import { refreshOverlay, setupOverlays } from "./overlays.js";

const $ = (id) => document.getElementById(id);
const screenEl = $("screen");
const REFRESH_MS = Number(screenEl.dataset.refreshSeconds) * 1000;

const state = {
  payload: null,          // the last good answer; it stays on screen if a request fails
  receivedAt: 0,          // performance.now() when it arrived
  requestFailed: false,
};
const trends = { loading: createTrendChart($("loadingChart")), cycle: createTrendChart($("cycleChart")) };

const secondsSinceAnswer = () => (performance.now() - state.receivedAt) / 1000;

// ------------------------------------------------------------------ Refresh loop

async function refresh() {
  try {
    const response = await fetch(screenEl.dataset.url, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.payload = await response.json();
    state.receivedAt = performance.now();
    state.requestFailed = false;
    render(state.payload);
  } catch (error) {
    state.requestFailed = true;
    renderLive();
  }
}

async function loop() {
  await refresh();
  setTimeout(loop, REFRESH_MS);     // the next request starts only after this one ended
}

function render(payload) {
  const today = payload.generated_at.slice(0, 10);
  const focused = document.activeElement?.dataset?.number;    // keep keyboard focus across refreshes

  renderLive();
  renderWeek(payload.week);
  $("clockDay").textContent = longDay(payload.generated_at);
  $("statusTotal").innerHTML = `<b>${renderPipeline($("statusBody"), payload.status_chart)}</b> ${esc(gettext("transports"))}`;
  renderGauges($("gauges"), payload.adherence_chart);
  $("adhDryCount").textContent = payload.adherence_chart.by_cargo_type.dry.count;
  $("adhColdCount").textContent = payload.adherence_chart.by_cargo_type.cold.count;
  updateTrendChart(trends.loading, payload.loading_chart);
  updateTrendChart(trends.cycle, payload.cycle_chart);
  $("loadingWeekAvg").textContent = duration(payload.loading_chart.week_average);
  $("cycleWeekAvg").textContent = duration(payload.cycle_chart.week_average);
  renderBays(payload.bays, today);
  renderIncoming(payload.incoming, payload.bays, today);
  tick();

  if (focused) document.querySelector(`[data-number="${CSS.escape(focused)}"]`)?.focus();
  refreshOverlay();
}

// ------------------------------------------------------------------ Header

function renderLive() {
  const payload = state.payload;
  if (!payload && !state.requestFailed) return;          // still connecting
  const stale = state.requestFailed || !payload || payload.data_is_stale;
  $("live").classList.toggle("stale", stale);
  $("liveState").textContent = stale ? `⚠ ${gettext("Data stale")}` : gettext("Live");
  $("lastUpdate").textContent = payload?.data_updated_at ? hhmmss(payload.data_updated_at) : gettext("unknown");
}

function renderWeek(week) {
  const share = week.workload ? week.dispatched / week.workload : 0;
  $("weekLabel").textContent = interpolate(gettext("Week %(range)s · dispatched"), { range: weekRange(week.start, week.end) }, true);
  $("weekDispatched").textContent = week.dispatched;
  $("weekWorkload").textContent = week.workload;
  $("weekBar").innerHTML = Array.from({ length: 24 }, (_, i) => `<i class="${i < Math.round(24 * share) ? "on" : ""}"></i>`).join("");
  $("weekPercent").textContent = week.workload ? `${Math.round(share * 100)}%` : "–";
  $("weekButton").setAttribute("aria-label", interpolate(
    gettext("Week counter: %(dispatched)s of %(workload)s dispatched. Open the completed list."), week, true));
}

/** Every second: the clock and the running timers advance; nothing else is recomputed. */
function tick() {
  const payload = state.payload;
  if (!payload) return;
  const passed = secondsSinceAnswer();
  const [h, m, s] = hhmmss(payload.generated_at).split(":").map(Number);
  $("clock").textContent = clock((h * 3600 + m * 60 + s + passed) % 86400);
  document.querySelectorAll("[data-elapsed]").forEach((el) => {
    el.textContent = clock(Number(el.dataset.elapsed) + passed);
  });
}

// ------------------------------------------------------------------ Hangar bays

function renderBays(bays, today) {
  const configured = bays.filter((bay) => bay.is_configured);
  const occupied = configured.filter((bay) => bay.transports.length).length;
  const occupancy = interpolate(gettext("%(occupied)s of %(total)s occupied"), { occupied, total: configured.length }, true);
  $("bayMap").innerHTML = configured.map((bay) => `<i class="${bay.transports.length ? "occ" : ""}"></i>`).join("");
  $("bayMap").setAttribute("aria-label", occupancy);
  $("bayOccupancy").textContent = occupancy;
  $("bays").innerHTML = bays.flatMap((bay) => (bay.transports.length
    ? bay.transports.map((row) => bayCard(bay.bay, row, today))
    : [freeCard(bay.bay)])).join("");
}

const bayNumber = (bay) => (bay === null || bay === undefined ? "?" : pad(bay));

function freeCard(bay) {
  const label = interpolate(gettext("Bay %(bay)s: free"), { bay }, true);
  return `<div class="card free cut" aria-label="${esc(label)}"><div class="ci cut">
      <div class="ch"><span class="bayno"><small>${esc(gettext("Bay"))}</small>${bayNumber(bay)}</span>
        <span class="st"><span class="lamp"></span>${esc(gettext("Free"))}</span></div>
      <div class="free-body"><span class="f1">${esc(gettext("Free"))}</span>
        <span class="sub">${esc(gettext("Ready for the next transport"))}</span></div>
    </div></div>`;
}

function bayCard(bay, row, today) {
  const label = interpolate(gettext("Bay %(bay)s, transport %(number)s, %(status)s. Open detail."),
    { bay: bayNumber(bay), number: row.number, status: STATUS[row.status] }, true);
  const lateClass = (outcome) => (outcome === "late" ? "is-late" : "");
  return `<article class="card row cut ${row.alerts.length ? "alert" : ""}" tabindex="0" role="button"
      data-number="${esc(row.number)}" data-source="board" aria-label="${esc(label)}">
    <div class="ci cut">
      <div class="ch"><span class="bayno"><small>${esc(gettext("Bay"))}</small>${bayNumber(bay)}</span>
        <span class="tno">${esc(row.number)}</span>${coldChip(row.cargo_type)}
        <span class="st"><span class="lamp" style="--l:${STATUS_COLORS[row.status].bg}"></span>${esc(STATUS[row.status])}</span></div>
      <div class="cb">
        ${alertChips(row.alerts)}
        <div class="kv">${esc(gettext("Appt"))} <b class="${lateClass(row.arrival_outcome)}">${esc(moment(row.appointment, today))}</b>
          ${badge(row.arrival_outcome)}${row.is_carryover ? `<span class="chip-carry">${esc(gettext("Carryover"))}</span>` : ""}</div>
        <div class="kv">${esc(gettext("Load start"))} <b class="${lateClass(row.loading_start_outcome)}">${esc(moment(row.planned_loading_start, today))}</b>
          ${badge(row.loading_start_outcome)}</div>
        ${timerBlock(row)}
        <div class="foot ${row.departure_overdue ? "overdue" : ""}">${esc(gettext("Departs by"))} <b>${esc(moment(row.planned_departure, today))}</b>
          ${row.departure_overdue ? `<span class="badge late">! ${esc(gettext("Overdue"))}</span>` : ""}</div>
        ${row.notes ? `<div class="notes">“${esc(row.notes)}”</div>` : ""}
      </div>
    </div></article>`;
}

function alertChips(alerts) {
  if (!alerts.length) return "";
  return `<div class="alerts">${alerts.map((a) => `<span class="alert-chip">⚠ ${esc(ALERT[a])}</span>`).join("")}</div>`;
}

const LEVEL_CHIP = { ok: `● ${gettext("OK")}`, warning: `▲ ${gettext("Warning")}`, critical: `■ ${gettext("Critical")}` };
const PAUSED_BY = { break: gettext("Break"), off_shift: gettext("Off shift") };

/** The loading timer, by timer.state (API-CONTRACT). */
function timerBlock(row) {
  const timer = row.timer;
  if (timer.state === "not_started") {
    return `<div class="timer"><div class="msg">${esc(gettext("Waiting for loading to start"))}</div></div>`;
  }
  if (timer.state === "missing_times") {
    return `<div class="timer"><div class="msg">${esc(gettext("Time not recorded"))}</div></div>`;
  }
  if (timer.state === "finished") {
    return `<div class="timer finished"><div class="row1"><span class="tt">${clock(timer.elapsed_seconds)}</span>
      <span class="lvl neutral">✓ ${esc(gettext("Done"))}</span></div>
      <div class="tsub">${esc(gettext("Total loading time"))}</div></div>`;
  }
  // running or paused: compared with its reference
  const running = timer.state === "running";
  const scale = timer.reference_minutes * 1.4;
  const fill = Math.min(timer.elapsed_seconds / 60 / scale, 1) * 100;
  const over = timer.over_reference_minutes;
  const delta = over < 0
    ? interpolate(gettext("%(time)s to the reference"), { time: duration(-over) }, true)
    : interpolate(gettext("%(time)s over the reference"), { time: duration(over) }, true);
  const reference = timer.reference_kind === "average"
    ? interpolate(gettext("%(cargo)s avg %(time)s"), { cargo: CARGO_NAME[row.cargo_type], time: duration(timer.reference_minutes) }, true)
    : interpolate(gettext("limit %(time)s"), { time: duration(timer.reference_minutes) }, true);
  const chip = running
    ? `<span class="lvl ${timer.level}">${esc(LEVEL_CHIP[timer.level])}</span>`
    : `<span class="lvl neutral" title="${esc(gettext("Paused"))}">❚❚ ${esc(PAUSED_BY[timer.paused_by])}</span>`;
  return `<div class="timer ${timer.level} ${timer.state}">
    <div class="row1"><span class="tt" ${running ? `data-elapsed="${timer.elapsed_seconds}"` : ""}>${clock(timer.elapsed_seconds)}</span>${chip}</div>
    <div class="bar"><i style="width:${fill}%"></i><span class="ref" style="left:${100 / 1.4}%"></span></div>
    <div class="tsub">${esc(delta)} · ${esc(reference)}</div></div>`;
}

const CARGO_NAME = { dry: gettext("dry"), cold: gettext("cold") };

// ------------------------------------------------------------------ Incoming

function renderIncoming(rows, bays, today) {
  const late = rows.filter((row) => row.is_late).length;
  $("incomingMeta").innerHTML = rows.length
    ? `<span>${esc(interpolate(ngettext("%(n)s transport", "%(n)s transports", rows.length), { n: rows.length }, true))}
       · <b>${esc(interpolate(gettext("%(n)s late"), { n: late }, true))}</b></span>`
    : "";
  if (!rows.length) {
    const nothingAtBays = bays.every((bay) => !bay.transports.length);
    const message = nothingAtBays ? gettext("Nothing at the bays and nothing incoming.") : gettext("Nothing incoming.");
    $("incoming").innerHTML = `<p class="empty-note">${esc(message)}</p>`;
    return;
  }
  const head = `<div class="irow ihead"><span class="col-grp">${esc(gettext("Group"))}</span><span>${esc(gettext("Transport"))}</span>
    <span>${esc(gettext("Status"))}</span><span>${esc(gettext("Appointment"))}</span>
    <span class="col-load">${esc(gettext("Load"))}</span><span class="col-dep">${esc(gettext("Departs"))}</span></div>`;
  $("incoming").innerHTML = head + rows.map((row) => incomingRow(row, today)).join("");
}

function incomingRow(row, today) {
  const second = [
    row.bay !== null ? interpolate(gettext("Bay %(bay)s assigned."), { bay: row.bay }, true) : "",
    row.is_carryover ? interpolate(gettext("Carryover · %(day)s."), { day: dayLabel(row.appointment) }, true) : "",
    row.notes,
  ].filter(Boolean).join(" ");
  const label = interpolate(gettext("%(number)s, %(status)s, %(group)s. Open detail."),
    { number: row.number, status: STATUS[row.status], group: GROUP[row.group] }, true);
  return `<div class="irow row ${row.is_late ? "late" : ""} ${row.alerts.length ? "hl" : ""}" tabindex="0" role="button"
      data-number="${esc(row.number)}" data-source="board" aria-label="${esc(label)}">
    <span class="grp ${esc(row.group)}">${esc(GROUP[row.group])}</span>
    <span class="tn"><span class="l1">${esc(row.number)}${coldChip(row.cargo_type)}</span>
      ${second ? `<span class="l2">${esc(second)}</span>` : ""}</span>
    <span class="stx"><span class="lamp" style="--l:${STATUS_COLORS[row.status].bg}"></span>${esc(STATUS[row.status])}</span>
    <span class="ap"><span class="tm ${row.arrival_outcome === "late" ? "is-late" : ""}">${esc(moment(row.appointment, today))}</span>${badge(row.arrival_outcome)}</span>
    <span class="tm col-load ${row.loading_start_outcome === "late" ? "is-late" : ""}">${esc(hhmm(row.planned_loading_start))}</span>
    <span class="tm col-dep ${row.departure_overdue ? "is-late" : ""}">${esc(hhmm(row.planned_departure))}</span>
  </div>`;
}

// ------------------------------------------------------------------ Wall mode

/** On a wide screen the board is a fixed 1920x1080 screen scaled to fit; otherwise it flows. */
function fitScreen() {
  const wall = innerWidth >= 1200 && innerWidth / innerHeight >= 1.5;
  document.body.classList.toggle("wall", wall);
  if (!wall) {
    screenEl.style.transform = screenEl.style.left = screenEl.style.top = "";
    return;
  }
  const scale = Math.min(innerWidth / 1920, innerHeight / 1080);
  screenEl.style.transform = `scale(${scale})`;
  screenEl.style.left = `${(innerWidth - 1920 * scale) / 2}px`;
  screenEl.style.top = `${(innerHeight - 1080 * scale) / 2}px`;
}

setupOverlays({ getPayload: () => state.payload, timerBlock });
fitScreen();
addEventListener("resize", fitScreen);
setInterval(tick, 1000);
loop();
