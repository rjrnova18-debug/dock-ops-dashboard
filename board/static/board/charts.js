// The board's charts: the status pipeline, the adherence gauges and the two trend lines.
//
// The pipeline and the gauges are plain HTML/SVG; the trends use Chart.js. Every function
// takes the matching part of the payload and draws it; none of them computes a rule.

/* global Chart, gettext, interpolate */
import { CARGO, CHECKPOINT, STATUS, dayLabel, duration, esc } from "../js/format.js";

// An ordinal blue ramp in the order of the visit: "scheduled" is the quietest.
// `fg` is the text colour that reads on each fill.
export const STATUS_COLORS = {
  scheduled: { bg: "#D5DDEA", fg: "#0B1B3A" }, waiting: { bg: "#A8C0EA", fg: "#0B1B3A" },
  inspected: { bg: "#7BA0E2", fg: "#0B1B3A" }, loading: { bg: "#2F5FC4", fg: "#FFFFFF" },
  loaded: { bg: "#234AA3", fg: "#FFFFFF" }, dispatched: { bg: "#1A3780", fg: "#FFFFFF" },
  in_transit: { bg: "#142B66", fg: "#FFFFFF" }, delivered: { bg: "#0E1F4A", fg: "#FFFFFF" },
};

const STAGE_OF = {
  scheduled: "incoming", waiting: "incoming", inspected: "at_bay", loading: "at_bay", loaded: "at_bay",
  dispatched: "dispatched", in_transit: "dispatched", delivered: "dispatched",
};
const STAGE = { incoming: gettext("Incoming"), at_bay: gettext("At bay"), dispatched: gettext("Dispatched") };

const CARGO_STYLE = {
  dry: { color: "#1D4ED8", point: "circle", radius: 4.5 },
  cold: { color: "#0891B2", point: "rectRot", radius: 6 },
};

// ------------------------------------------------------------------ Status pipeline

/** One segment per status, sized by its count, under brackets for the three stages. */
export function renderPipeline(container, statusChart) {
  const counts = statusChart.counts;
  const total = counts.reduce((sum, item) => sum + item.count, 0);
  if (!total) {
    container.innerHTML = `<p class="empty-note">${esc(gettext("No transports in today's operation yet."))}</p>`;
    return total;
  }
  const stages = [];
  for (const { status, count } of counts) {
    const last = stages[stages.length - 1];
    if (last && last.stage === STAGE_OF[status]) last.count += count;
    else stages.push({ stage: STAGE_OF[status], count });
  }
  const description = counts.map(({ status, count }) => `${STATUS[status]} ${count}`).join(", ");

  container.innerHTML = `
    <div class="groups" aria-hidden="true">${stages.map((s) =>
      `<div class="grp-span" style="flex-grow:${s.count}">${esc(STAGE[s.stage])}</div>`).join("")}</div>
    <div class="pipe" role="img" aria-label="${esc(description)}">${counts.map(({ status, count }) => {
      const share = Math.round((count / total) * 100);
      return `<div class="seg" style="flex-grow:${count};--s:${STATUS_COLORS[status].bg};--t:${STATUS_COLORS[status].fg}"
                   title="${esc(STATUS[status])}: ${count} (${share}%)">
                <span class="n">${count}</span><span class="nm">${esc(STATUS[status])}</span></div>`;
    }).join("")}</div>
    <div class="legend">${counts.map(({ status }) =>
      `<span><i class="sw" style="background:${STATUS_COLORS[status].bg}"></i>${esc(STATUS[status])}</span>`).join("")}</div>`;

  // A segment too narrow for its name shows only the count; the legend names it.
  requestAnimationFrame(() => container.querySelectorAll(".seg")
    .forEach((seg) => seg.classList.toggle("narrow", seg.clientWidth < 130)));
  return total;
}

// ------------------------------------------------------------------ Adherence gauges

/** Five arc gauges: the arc is all transports, the circle is dry and the diamond is cold. */
export function renderGauges(container, adherence) {
  const { dry, cold } = adherence.by_cargo_type;
  container.innerHTML = adherence.checkpoints.map((checkpoint, i) => {
    const label = CHECKPOINT[checkpoint];
    const svg = gaugeSvg(label, adherence.percent[i],
      dry.count ? dry.percent[i] : null, cold.count ? cold.percent[i] : null);
    return `<div class="gauge">${svg}<div class="gl">${esc(label)}</div></div>`;
  }).join("");
}

function gaugeSvg(label, all, dry, cold) {
  const cx = 60, cy = 58, R = 42;
  const point = (percent, radius = R) => {
    const angle = ((135 + 2.7 * percent) * Math.PI) / 180;
    return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
  };
  const [sx, sy] = point(0);
  const [ex, ey] = point(100);
  const arc = `M ${sx.toFixed(2)} ${sy.toFixed(2)} A ${R} ${R} 0 1 1 ${ex.toFixed(2)} ${ey.toFixed(2)}`;
  const ends = [0, 100].map((p) => {
    const [x1, y1] = point(p, R + 7), [x2, y2] = point(p, R + 12);
    return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#AFBCD2" stroke-width="1.5"/>`;
  }).join("");

  if (all === null) {                          // no data yet: never drawn as 0 %
    const title = interpolate(gettext("%(checkpoint)s: no data yet"), { checkpoint: label }, true);
    return `<svg viewBox="0 0 120 104" role="img" aria-label="${esc(title)}"><title>${esc(title)}</title>
      <path d="${arc}" fill="none" stroke="#C3CEDF" stroke-width="9" stroke-dasharray="1.6 2.4" pathLength="100"/>${ends}
      <text x="60" y="62" text-anchor="middle" font-family="Chakra Petch" font-weight="700" font-size="24" fill="#56668A">—</text>
      <text x="60" y="80" text-anchor="middle" font-family="Chakra Petch" font-weight="600" font-size="8.5" letter-spacing="1.4" fill="#56668A">${esc(gettext("NO DATA"))}</text></svg>`;
  }

  const parts = [`${label}: ${all}%`];
  if (dry !== null) parts.push(`${CARGO.dry} ${dry}%`);
  if (cold !== null) parts.push(`${CARGO.cold} ${cold}%`);
  const title = parts.join(" · ");
  const ticks = [25, 50, 75].map((p) => {
    const [x1, y1] = point(p, R - 6), [x2, y2] = point(p, R + 6);
    return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#fff" stroke-width="1.5"/>`;
  }).join("");
  let markers = "";
  if (dry !== null) {
    const [x, y] = point(dry, R + 10);
    markers += `<circle cx="${x}" cy="${y}" r="4.6" fill="#1D4ED8" stroke="#fff" stroke-width="2"/>`;
  }
  if (cold !== null) {
    const [x, y] = point(cold, R - 11);
    markers += `<rect x="${x - 4}" y="${y - 4}" width="8" height="8" fill="#0891B2" stroke="#fff" stroke-width="2" transform="rotate(45 ${x} ${y})"/>`;
  }
  return `<svg viewBox="0 0 120 104" role="img" aria-label="${esc(title)}"><title>${esc(title)}</title>
    <path d="${arc}" fill="none" stroke="#DCE6F8" stroke-width="9" pathLength="100"/>
    <path d="${arc}" fill="none" stroke="#123C99" stroke-width="9" pathLength="100" stroke-dasharray="${all} 100"/>
    ${ticks}${ends}${markers}
    <text x="60" y="64" text-anchor="middle" font-family="Chakra Petch" font-weight="700" font-size="27" fill="#0B1B3A">${all}<tspan font-size="13" dx="1">%</tspan></text></svg>`;
}

// ------------------------------------------------------------------ Trend lines

const toHours = (minutes) => (minutes === null ? null : minutes / 60);

/** An empty trend chart: one line per cargo type plus its dashed week average. */
export function createTrendChart(canvas) {
  Chart.defaults.font.family = "'IBM Plex Sans', sans-serif";
  Chart.defaults.color = "#33456A";
  const lines = ["dry", "cold"].map((cargo) => {
    const style = CARGO_STYLE[cargo];
    return {
      label: CARGO[cargo], cargo, data: [], borderColor: style.color, backgroundColor: style.color,
      borderWidth: 2, pointStyle: style.point, pointRadius: style.radius, pointHoverRadius: style.radius + 2,
      pointBorderColor: "#fff", pointBorderWidth: 2, spanGaps: true,   // a missing day is bridged, never 0
    };
  });
  const averages = ["dry", "cold"].map((cargo) => ({
    label: CARGO[cargo], cargo, isAverage: true, data: [], borderColor: CARGO_STYLE[cargo].color,
    borderWidth: 1.5, borderDash: [6, 5], pointRadius: 0, pointHoverRadius: 0,
  }));

  return new Chart(canvas, {
    type: "line",
    data: { labels: [], datasets: [...lines, ...averages] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },     // no need to hit a point exactly
      scales: {
        y: { beginAtZero: true, grid: { color: "#E3E9F3" }, border: { display: false },
             ticks: { stepSize: 1, font: { size: 11 }, callback: (v) => interpolate(gettext("%(h)s h"), { h: v }, true) } },
        x: { grid: { display: false }, ticks: { font: { size: 11 } } },
      },
      plugins: {
        legend: {
          position: "top", align: "end",
          labels: {
            usePointStyle: true, boxWidth: 8, boxHeight: 8, font: { size: 11 },
            filter: (item, data) => !data.datasets[item.datasetIndex].isAverage,
            generateLabels: (chart) => Chart.defaults.plugins.legend.labels.generateLabels(chart).map((item) => {
              const dataset = chart.data.datasets[item.datasetIndex];
              if (dataset.isAverage) return item;
              const average = interpolate(gettext("week avg %(time)s"), { time: duration(dataset.weekAverage) }, true);
              return { ...item, text: `${dataset.label}  ┄ ${average}` };
            }),
          },
          // Hiding a cargo type hides its line and its average line.
          onClick: (event, item, legend) => {
            const chart = legend.chart;
            const cargo = chart.data.datasets[item.datasetIndex].cargo;
            const show = !chart.isDatasetVisible(item.datasetIndex);
            chart.data.datasets.forEach((dataset, i) => { if (dataset.cargo === cargo) chart.setDatasetVisibility(i, show); });
            chart.update();
          },
        },
        tooltip: {
          usePointStyle: true, boxPadding: 4,
          filter: (item) => !item.dataset.isAverage && item.raw !== null,
          callbacks: { label: (item) => ` ${item.dataset.label}: ${duration(item.raw * 60)}` },
        },
      },
    },
  });
}

/** New data into an existing chart, keeping whatever the viewer has hidden. */
export function updateTrendChart(chart, trend) {
  chart.data.labels = trend.days.map(dayLabel);
  for (const dataset of chart.data.datasets) {
    const series = trend.by_cargo_type[dataset.cargo];
    dataset.weekAverage = series.week_average;
    dataset.data = dataset.isAverage
      ? trend.days.map(() => toHours(series.week_average))
      : series.daily_average.map(toHours);
  }
  chart.update("none");
}
