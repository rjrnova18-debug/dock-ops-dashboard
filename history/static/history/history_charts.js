// The history's charts (Chart.js) over the series and the checkpoint breakdown, and the
// same numbers as tables. Every chart is created once and then refilled, so whatever the
// viewer hid through a legend stays hidden when the filters change.

/* global Chart, gettext, interpolate */
import { CARGO, CHECKPOINT, duration, esc, pad, parseIso } from "../js/format.js";

const CARGOS = ["dry", "cold"];
const STYLE = {
  dry: { color: "#1D4ED8", point: "circle", radius: 4 },
  cold: { color: "#0891B2", point: "rectRot", radius: 5.5 },
};
const LANG = document.documentElement.lang || "en";
const charts = {};

/** A diagonal hatch for the cold bars: the two cargo types never differ by colour alone. */
function hatch(color) {
  const tile = document.createElement("canvas");
  tile.width = tile.height = 8;
  const pen = tile.getContext("2d");
  pen.fillStyle = `${color}33`;
  pen.fillRect(0, 0, 8, 8);
  pen.strokeStyle = color;
  pen.lineWidth = 2;
  pen.beginPath();
  pen.moveTo(0, 8); pen.lineTo(8, 0); pen.moveTo(-2, 2); pen.lineTo(2, -2); pen.moveTo(6, 10); pen.lineTo(10, 6);
  pen.stroke();
  return pen.createPattern(tile, "repeat");
}

/** The label of a bucket key: "Mon 3", "Week of 03 Nov", "Nov 2026". */
export function bucketLabel(key, groupBy) {
  if (groupBy === "month") {
    return new Intl.DateTimeFormat(LANG, { month: "short", year: "numeric" }).format(parseIso(`${key}-01`));
  }
  const day = parseIso(key);
  if (groupBy === "week") {
    const month = new Intl.DateTimeFormat(LANG, { month: "short" }).format(day);
    return interpolate(gettext("Week of %(day)s"), { day: `${pad(day.getDate())} ${month}` }, true);
  }
  return `${new Intl.DateTimeFormat(LANG, { weekday: "short" }).format(day)} ${day.getDate()}`;
}

// ------------------------------------------------------------------ Creating the charts

function create(name, type, { stacked = false, max, tick }) {
  Chart.defaults.font.family = "'IBM Plex Sans', sans-serif";
  Chart.defaults.color = "#33456A";
  const datasets = CARGOS.map((cargo) => {
    const style = STYLE[cargo];
    const common = { label: CARGO[cargo], cargo, data: [], borderColor: style.color };
    return type === "bar"
      ? { ...common, backgroundColor: cargo === "cold" ? hatch(style.color) : style.color, borderWidth: cargo === "cold" ? 1.5 : 0,
          maxBarThickness: 28, borderRadius: 2 }
      : { ...common, backgroundColor: style.color, borderWidth: 2, pointStyle: style.point, pointRadius: style.radius,
          pointHoverRadius: style.radius + 2, pointBorderColor: "#fff", pointBorderWidth: 2, spanGaps: true };
  });
  charts[name] = new Chart(document.getElementById(`chart-${name}`), {
    type,
    data: { labels: [], datasets },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { stacked, grid: { display: false }, ticks: { font: { size: 11 } } },
        y: { stacked, beginAtZero: true, max, grid: { color: "#E3E9F3" }, border: { display: false },
             ticks: { font: { size: 11 }, callback: tick } },
      },
      plugins: {
        legend: {
          position: "top", align: "end",
          labels: { usePointStyle: type === "line", boxWidth: 10, boxHeight: 10, font: { size: 11 },
                    filter: (item, data) => data.datasets[item.datasetIndex].data.length > 0 },   // a filtered-out cargo type
        },
        tooltip: { usePointStyle: true, boxPadding: 4, filter: (item) => item.raw !== null },
      },
    },
  });
}

const hours = (v) => interpolate(gettext("%(h)s h"), { h: v }, true);
const percent = (v) => `${v}%`;

export function createCharts() {
  create("dispatched", "bar", { stacked: true });
  create("adherence", "line", { max: 100, tick: percent });
  create("loading", "line", { tick: hours });
  create("cycle", "line", { tick: hours });
  create("checkpoints", "bar", { max: 100, tick: percent });
  charts.loading.options.plugins.tooltip.callbacks = { label: (i) => ` ${i.dataset.label}: ${duration(i.raw * 60)}` };
  charts.cycle.options.plugins.tooltip.callbacks = { label: (i) => ` ${i.dataset.label}: ${duration(i.raw * 60)}` };
}

// ------------------------------------------------------------------ Filling them

function refill(name, labels, valueOf, visible) {
  const chart = charts[name];
  chart.data.labels = labels;
  for (const dataset of chart.data.datasets) {
    dataset.data = visible.includes(dataset.cargo) ? valueOf(dataset.cargo) : [];
  }
  chart.update("none");
}

const toHours = (minutes) => (minutes === null ? null : minutes / 60);

/** The four series charts and the checkpoint chart, with their tables. */
export function renderCharts(summary, visible) {
  const { series, group_by: groupBy } = summary;
  const labels = series.map((bucket) => bucketLabel(bucket.key, groupBy));
  const each = (indicator, convert = (v) => v) => (cargo) =>
    series.map((bucket) => convert(bucket.by_cargo_type[cargo][indicator]));

  refill("dispatched", labels, each("dispatched"), visible);
  refill("adherence", labels, each("adherence_percent"), visible);
  refill("loading", labels, each("loading_average_minutes", toHours), visible);
  refill("cycle", labels, each("cycle_average_minutes", toHours), visible);
  refill("checkpoints", summary.checkpoints.map((c) => CHECKPOINT[c.checkpoint]),
    (cargo) => summary.checkpoints.map((c) => c.by_cargo_type[cargo]), visible);

  const count = (v) => String(v);
  const pct = (v) => (v === null ? "–" : `${v}%`);
  seriesTable("dispatched", summary, labels, visible, "dispatched", count);
  seriesTable("adherence", summary, labels, visible, "adherence_percent", pct);
  seriesTable("loading", summary, labels, visible, "loading_average_minutes", duration);
  seriesTable("cycle", summary, labels, visible, "cycle_average_minutes", duration);
  checkpointTable(summary, visible);
}

// ------------------------------------------------------------------ Tables

const tableHtml = (head, rows) =>
  `<table class="t"><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;

function seriesTable(name, summary, labels, visible, indicator, show) {
  const head = [gettext("Period"), ...visible.map((cargo) => CARGO[cargo]), gettext("Total")];
  const rows = summary.series.map((bucket, i) => `<tr><td>${esc(labels[i])}</td>${
    visible.map((cargo) => `<td>${esc(show(bucket.by_cargo_type[cargo][indicator]))}</td>`).join("")
  }<td><b>${esc(show(bucket[indicator]))}</b></td></tr>`);
  document.getElementById(`table-${name}`).innerHTML = summary.series.length
    ? tableHtml(head, rows) : `<p class="empty-note">${esc(gettext("No data in this period."))}</p>`;
}

function checkpointTable(summary, visible) {
  const head = [gettext("Checkpoint"), gettext("Adherence"), gettext("On time"), gettext("Late"), gettext("No plan"),
    gettext("Pending"), ...visible.map((cargo) => CARGO[cargo])];
  const pct = (v) => (v === null ? "–" : `${v}%`);
  const rows = summary.checkpoints.map((c) => `<tr><td>${esc(CHECKPOINT[c.checkpoint])}</td><td><b>${pct(c.percent)}</b></td>
    <td>${c.on_time}</td><td>${c.late}</td><td>${c.no_plan}</td><td>${c.pending}</td>
    ${visible.map((cargo) => `<td>${pct(c.by_cargo_type[cargo])}</td>`).join("")}</tr>`);
  document.getElementById("table-checkpoints").innerHTML = tableHtml(head, rows);
}
