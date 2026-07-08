/**
 * Fast (canvas-based) chart rendering with Apache ECharts.
 *
 * This module offers an alternative to the Vega-Lite charts for users who want
 * snappier rendering and interaction on dense time series:
 * - canvas rendering (no per-mark DOM nodes)
 * - built-in LTTB downsampling per line series (`sampling: "lttb"`)
 * - mouse-wheel zoom, drag-to-pan and a range slider, synced across subplots
 *
 * It consumes the same rows as the Vega-Lite charts (the decompressed output
 * of the /chart_data endpoints): objects with `event_start` (ms epoch),
 * `event_value`, `belief_horizon` (ms), and nested `sensor` and `source`
 * objects. Layout, chart types and tooltips mirror the Vega-Lite charts:
 * - line/bar charts with centered subplot titles and "Sensor-type (unit)" y-axis titles
 * - histogram (binned values per source) and daily/weekly heatmaps
 *   (most prevalent source, diverging color scale centered at 0)
 * - per-point tooltips listing sensor, value, time, horizon and source details
 * - replay support (belief-time ruler), legends beside or below each subplot,
 *   and CSV/SVG/PNG export from the toolbox
 *
 * Dependencies: the global `echarts` object (loaded in base.html).
 */

import { convertToCSV } from "./data-utils.js";

// Global text style matching Vega-Lite: Poppins font, 16 px labels (Vega's FONT_SIZE = 16)
const CHART_FONT = "Poppins, sans-serif";
const FONT_SIZE = 16;

const GRID_HEIGHT = 220; // height of each subplot in px
const SIDE_GRID_GAP = 82; // vertical space between subplots (two-line x-axis labels + next title)
const TOP_OFFSET = 48; // room for the toolbox and the first subplot title
const BOTTOM_OFFSET = 92; // room for the slider and the last two-line x-axis labels
const GRID_LEFT = 70; // room for the y-axis labels
const LEGEND_WIDTH = 220; // width of the legend column beside each subplot

// Diverging color scale approximating Vega's "blueorange" scheme (centered at 0)
const BLUE_ORANGE = ["#2166ac", "#67a9cf", "#d1e5f0", "#f7f7f7", "#fee0b6", "#f1a340", "#b35806"];

// One chart instance per container element
const instances = {};

/* ============================== formatting ============================== */

// Build a label for a single source. Mirrors the Vega-Lite "source_legend_label"
// transform: keep source.name visible, and only when sources share a name do we
// fall back (handled in computeSourceLabels). On its own this returns the name.
function sourceLabel(source) {
  return source.name || "source " + source.id;
}

// Compute legend labels for a set of sources, mirroring the Vega-Lite chart:
// show only source.name when names are unique, and append the shortest
// distinguishing detail (type / model / version, else the id) when they collide.
// Returns a Map keyed by source.id.
function computeSourceLabels(sources) {
  const byId = new Map();
  for (const s of sources) {
    if (s && s.id != null) byId.set(s.id, s);
  }
  const uniqueSources = Array.from(byId.values());

  const nameCount = new Map();
  for (const s of uniqueSources) {
    const name = s.name || "source " + s.id;
    nameCount.set(name, (nameCount.get(name) || 0) + 1);
  }

  const labels = new Map();
  for (const s of uniqueSources) {
    const name = s.name || "source " + s.id;
    if (nameCount.get(name) === 1) {
      labels.set(s.id, name); // unique name → just the name, as in Vega-Lite
      continue;
    }
    // Duplicate names: append the shortest available distinguishing detail.
    const detail =
      s.display_type || s.type || s.model || (s.version ? "v" + s.version : "");
    labels.set(s.id, detail ? name + " (" + detail + ")" : name + " (ID: " + s.id + ")");
  }
  return labels;
}

function capFirst(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

// "Source" key with little line samples (dotted/dashed/solid + label per type),
// mirroring the Vega-Lite charts' Source legend. Returns one ECharts graphic
// group laid out as a vertical column ("Source" title, then one row per source
// type) placed at the bottom-left, exactly as the Vega-Lite charts render it.
const SOURCE_KEY_ROW_HEIGHT = 20;
// Title row + one row per source type (forecaster, scheduler, other — see
// SOURCE_KEY_ROWS below); reserve this height at the bottom for the key.
const SOURCE_KEY_HEIGHT = 24 + 3 * SOURCE_KEY_ROW_HEIGHT;

function buildSourceKey(left, top) {
  const children = [
    {
      type: "text",
      left: 0,
      top: 0,
      style: { text: "Source", font: "bold 12px sans-serif", fill: "#222" },
    },
  ];
  let y = 24;
  for (const row of SOURCE_KEY_ROWS) {
    children.push({
      type: "line",
      shape: { x1: 0, y1: y + 6, x2: 30, y2: y + 6 },
      style: { stroke: "#555", lineWidth: 1.5, lineDash: row.dash || null },
    });
    children.push({
      type: "text",
      left: 38,
      top: y,
      style: { text: row.label, fontSize: 11, fill: "#222" },
    });
    y += SOURCE_KEY_ROW_HEIGHT;
  }
  return { type: "group", left: left, top: top, children: children };
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );
}

// Quantity formatting as in the Vega-Lite charts: space as thousands separator
function formatQuantity(value, unit) {
  const formatted = (+value.toFixed(4))
    .toLocaleString("en-US", { maximumFractionDigits: 4 })
    .replace(/,/g, " ");
  return unit ? formatted + " " + unit : formatted;
}

// Same as the Vega-Lite charts' TIME_FORMAT: "%H:%M on %A %b %e, %Y"
const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function formatFullDate(ms) {
  const d = new Date(ms);
  const pad = (n) => String(n).padStart(2, "0");
  return (
    pad(d.getHours()) + ":" + pad(d.getMinutes()) +
    " on " + DAY_NAMES[d.getDay()] + " " + MONTH_NAMES[d.getMonth()] +
    " " + d.getDate() + ", " + d.getFullYear()
  );
}

function formatDate(ms) {
  const d = new Date(ms);
  return MONTH_NAMES[d.getMonth()] + " " + d.getDate() + ", " + d.getFullYear();
}

// Port of the timedeltaFormat used by the Vega-Lite tooltips (breakpoint 4)
function formatTimedelta(ms) {
  if (typeof ms !== "number" || isNaN(ms)) {
    return "";
  }
  const Y = 1000 * 60 * 60 * 24 * 365.2425;
  const D = 1000 * 60 * 60 * 24;
  const H = 1000 * 60 * 60;
  const M = 1000 * 60;
  const S = 1000;
  const abs = Math.abs(ms);
  return abs > 4 * Y ? Math.round(ms / Y) + " years"
    : abs > 4 * D ? Math.round(ms / D) + " days"
    : abs > 4 * H ? Math.round(ms / H) + " hours"
    : abs > 4 * M ? Math.round(ms / M) + " minutes"
    : abs > 4 * S ? Math.round(ms / S) + " seconds"
    : Math.round(ms) + " milliseconds";
}

function tooltipTable(rows) {
  return (
    '<table style="font-size:12px;line-height:1.6;">' +
    rows
      .map(
        (r) =>
          '<tr><td style="color:#888;text-align:right;padding-right:12px;white-space:nowrap;">' +
          escapeHtml(r[0]) +
          '</td><td style="max-width:280px;white-space:normal;">' +
          escapeHtml(r[1]) +
          "</td></tr>"
      )
      .join("") +
    "</table>"
  );
}

/* ============================== data grouping ============================== */

function numericRows(data) {
  return (data || []).filter((row) => typeof row.event_value === "number");
}

/**
 * Group chart data rows into subplots and series (one series per
 * sensor+source combination).
 *
 * When a group spec is given (the asset's sensors_to_show structure), the
 * subplots mirror the Vega-Lite chart: one subplot per spec entry, in order,
 * each with its title and sensors. Spec entries without data still get an
 * (empty) subplot, so no chart goes missing. Rows from sensors not covered
 * by the spec — and all rows when there is no spec — are grouped by unit.
 *
 * @param {Object[]} data - Decompressed chart data rows.
 * @param {Object[]} [groupSpec] - Optional subplot structure: [{ title, sensorIds, sensorType }].
 * @returns {Object[]} - List of groups: { title, units, sensorType, multiSensor, series }.
 */
function groupData(data, groupSpec) {
  const groups = [];
  const groupBySensorId = new Map();
  const groupByUnit = new Map(); // fallback for rows not covered by the spec

  function newGroup(title, sensorType) {
    const group = {
      title: title,
      sensorType: sensorType || "",
      units: new Set(),
      sensorNames: new Set(),
      series: new Map(),
    };
    groups.push(group);
    return group;
  }

  if (Array.isArray(groupSpec)) {
    for (const entry of groupSpec) {
      const group = newGroup(entry.title || "", entry.sensorType || "");
      for (const sensorId of entry.sensorIds || []) {
        groupBySensorId.set(sensorId, group);
      }
    }
  }

  for (const row of numericRows(data)) {
    const sensor = row.sensor || {};
    const source = row.source || {};
    const unit = sensor.unit || row.sensor_unit || "";
    let group = groupBySensorId.get(sensor.id);
    if (!group) {
      group = groupByUnit.get(unit) || groupByUnit.set(unit, newGroup("", "")).get(unit);
    }
    group.units.add(unit);
    group.sensorNames.add(sensor.name || "sensor " + sensor.id);
    const seriesKey = sensor.id + "|" + source.id;
    if (!group.series.has(seriesKey)) {
      group.series.set(seriesKey, {
        sensorName: sensor.name || "sensor " + sensor.id,
        sensorDescription: sensor.description || sensor.name || "",
        sourceLabel: sourceLabel(source),
        source: source,
        unit: unit,
        // The sensor's real event resolution in seconds (0 = instantaneous),
        // as sent by Sensor.as_dict; undefined for legacy data, in which case we
        // fall back to inferring it from the event spacing.
        eventResolutionSec:
          typeof sensor.event_resolution === "number" ? sensor.event_resolution : null,
        points: [],
        eventStarts: [], // kept for resolution inference (not sent to ECharts)
      });
    }
    const ser = group.series.get(seriesKey);
    // Third dimension carries the belief horizon (ms) for the tooltip;
    // LTTB sampling selects original points, so it survives downsampling.
    ser.points.push([row.event_start, row.event_value, row.belief_horizon]);
    ser.eventStarts.push(row.event_start);
  }

  // Mirror the Vega-Lite legend encoding:
  // - multi-sensor (asset) charts: one legend entry per sensor, labeled
  //   "sensor (asset)", with sources distinguished by line style;
  // - single-sensor (sensor page) charts: one legend entry per source.
  const uniqueSensorKeys = new Set();
  for (const group of groups) {
    for (const s of group.series.values()) {
      uniqueSensorKeys.add(s.sensorDescription || s.sensorName);
    }
  }
  const nameBySensor = uniqueSensorKeys.size > 1;

  // Source legend labels, disambiguated only when names collide (as in Vega-Lite).
  const allSources = [];
  for (const group of groups) {
    for (const s of group.series.values()) allSources.push(s.source);
  }
  const sourceLabels = computeSourceLabels(allSources);

  return groups.map((group) => {
    const series = [];
    for (const s of group.series.values()) {
      s.points.sort((a, b) => a[0] - b[0]);
      // Series sharing a name (same sensor, several sources) toggle together
      // via their shared legend entry, as in the Vega-Lite charts.
      const srcLabel =
        (s.source && sourceLabels.get(s.source.id)) || s.sourceLabel;
      s.name = nameBySensor ? s.sensorDescription || s.sensorName : srcLabel;
      s.sensorType = group.sensorType || s.sensorName;
      series.push(s);
    }
    const sensorNames = Array.from(group.sensorNames);
    return {
      title: group.title || sensorNames.join(", "),
      units: Array.from(group.units),
      sensorType: group.sensorType,
      multiSensor: group.sensorNames.size > 1,
      nameBySensor: nameBySensor,
      series: series,
    };
  });
}

// Colors per sensor, matching the Vega-Lite charts' category scheme
// Vega-Lite's default categorical color scheme (tableau10), so sensor colors match the old charts
const SENSOR_COLORS = [
  "#4c78a8", "#f58518", "#e45756", "#72b7b2", "#54a24b",
  "#eeca3b", "#b279a2", "#ff9da6", "#9d755d", "#bab0ac",
];

// Line styles per source type, as in the Vega-Lite charts' "Source" legend.
// The three rows of the source key below must list these same dash patterns.
const SOURCE_KEY_ROWS = [
  { label: "forecaster", dash: [2, 3] },
  { label: "scheduler", dash: [7, 4] },
  { label: "other", dash: null }, // solid
];

function lineTypeForSource(source) {
  const type = String(source.display_type || source.type || "").toLowerCase();
  if (type.includes("forecast")) {
    return "dotted";
  }
  if (type.includes("schedul")) {
    return "dashed";
  }
  return "solid";
}

// Keep only the rows of the source with the most data (as the Vega-Lite heatmaps do)
function mostPrevalentSourceRows(rows) {
  const counts = new Map();
  for (const row of rows) {
    const sid = row.source ? row.source.id : null;
    counts.set(sid, (counts.get(sid) || 0) + 1);
  }
  let bestSid = null;
  let bestCount = -1;
  for (const [sid, count] of counts) {
    if (count > bestCount) {
      bestSid = sid;
      bestCount = count;
    }
  }
  return rows.filter((row) => (row.source ? row.source.id : null) === bestSid);
}

// Smallest positive gap between consecutive event starts (the sensor resolution).
// Accepts either raw data rows (with .event_start) or a plain array of timestamps.
function inferResolutionMs(rowsOrTimestamps) {
  const starts = Array.from(
    new Set(
      rowsOrTimestamps.map((x) => (typeof x === "number" ? x : x.event_start))
    )
  ).sort((a, b) => a - b);
  let res = Infinity;
  for (let i = 1; i < starts.length; i++) {
    const gap = starts[i] - starts[i - 1];
    if (gap > 0 && gap < res) res = gap;
  }
  if (!isFinite(res)) res = 60 * 60 * 1000;
  return Math.max(res, 60 * 1000); // at least 1 minute, to bound the number of cells
}

/* ============================== chart parts ============================== */

function yAxisTitle(sensorType, units) {
  const unitLabel = units.join(", ");
  return sensorType
    ? capFirst(sensorType) + (unitLabel ? " (" + unitLabel + ")" : "")
    : unitLabel;
}

// Mixed date/time x-axis labels shared by every time-axis chart: "HH:MM" normally,
// falling back to the day name + date at midnight, and the month name on the 1st.
function xAxisTimeFormatter(value) {
  const d = new Date(value);
  const h = d.getHours(), m = d.getMinutes();
  if (h === 0 && m === 0) {
    const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    if (d.getDate() === 1) return MONTHS[d.getMonth()];
    return DAYS[d.getDay()] + "\n" + String(d.getDate()).padStart(2, "0");
  }
  return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0");
}

function toolboxFeatures(elementId, datasetName, isSensorPage) {
  const dataZoom = { yAxisIndex: false };
  const savePNG = {
    show: true,
    title: "Save as PNG",
    icon: "path://M4 5 L20 5 L20 19 L4 19 Z M8 14 L11 10 L13 13 L15 11 L18 15 L8 15 Z",
    onclick: () => exportPNG(elementId, datasetName),
  };
  const saveCSV = {
    show: true,
    title: "Save as CSV",
    icon: "path://M5 2 L13 2 L17 6 L17 20 L5 20 Z M7 11 L15 11 M7 14 L15 14 M7 17 L15 17",
    onclick: () => exportCSV(elementId, datasetName),
  };
  const saveSVG = {
    show: true,
    title: "Save as SVG",
    icon: "path://M5 2 L13 2 L17 6 L17 20 L5 20 Z M7 12 L11 17 L15 9",
    onclick: () => exportSVG(elementId, datasetName),
  };
  // Toolbox icons render in key order. On the sensor page, place SVG between the
  // dataZoom (zoom/reset) icons and PNG; elsewhere keep PNG, CSV, SVG.
  const feature = isSensorPage
    ? { dataZoom: dataZoom, mySaveSVG: saveSVG, mySavePNG: savePNG, mySaveCSV: saveCSV }
    : { dataZoom: dataZoom, mySavePNG: savePNG, mySaveCSV: saveCSV, mySaveSVG: saveSVG };
  return { right: 16, feature: feature };
}

function downloadBlob(content, mimeType, filename) {
  const blob = new Blob([content], { type: mimeType });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

function exportCSV(elementId, datasetName) {
  const instance = instances[elementId];
  if (!instance || !instance.lastArgs) {
    return;
  }
  const csv = convertToCSV(instance.lastArgs.data || []);
  // convertToCSV prefixes the (unencoded) CSV content with a data-URI scheme
  const prefix = "data:text/csv;charset=utf-8,";
  const content = csv.startsWith(prefix) ? csv.slice(prefix.length) : csv;
  downloadBlob(content, "text/csv;charset=utf-8", (datasetName || "chart") + ".csv");
}

// Build the option used for image exports: no toolbox buttons, and "scroll"
// legends switched to "plain" so every entry renders instead of just one page.
function buildExportOption(lastOption) {
  const legend = (
    Array.isArray(lastOption.legend)
      ? lastOption.legend
      : lastOption.legend
      ? [lastOption.legend]
      : []
  ).map((l) => Object.assign({}, l, { type: "plain" }));
  // Render every series in a single synchronous pass. Heatmaps use progressive
  // rendering (cells drawn across animation frames); the export reads the
  // canvas/SVG immediately after setOption, so without this a large heatmap
  // (e.g. a year of data, > 5000 cells) loses every cell past the first chunk.
  const series = (
    Array.isArray(lastOption.series)
      ? lastOption.series
      : lastOption.series
      ? [lastOption.series]
      : []
  ).map((s) => Object.assign({}, s, { progressive: 0, animation: false }));
  return Object.assign({}, lastOption, {
    animation: false,
    backgroundColor: "#fff",
    toolbox: { show: false },
    legend: legend,
    series: series,
  });
}

function exportSVG(elementId, datasetName) {
  const instance = instances[elementId];
  if (!instance || !instance.lastOption || typeof echarts === "undefined") {
    return;
  }
  // Render the current option to SVG with a temporary server-side-rendering instance
  const svgChart = echarts.init(null, null, {
    renderer: "svg",
    ssr: true,
    width: instance.chart.getWidth(),
    height: instance.chart.getHeight(),
  });
  try {
    svgChart.setOption(buildExportOption(instance.lastOption));
    downloadBlob(svgChart.renderToSVGString(), "image/svg+xml", (datasetName || "chart") + ".svg");
  } finally {
    svgChart.dispose();
  }
}

function exportPNG(elementId, datasetName) {
  const instance = instances[elementId];
  if (!instance || !instance.lastOption || typeof echarts === "undefined") {
    return;
  }
  // Render to a detached canvas instance so the saved PNG shows all legend
  // entries and no toolbox, instead of snapshotting the paginated on-screen chart.
  const holder = document.createElement("div");
  holder.style.width = instance.chart.getWidth() + "px";
  holder.style.height = instance.chart.getHeight() + "px";
  const pngChart = echarts.init(holder, null, { renderer: "canvas" });
  try {
    pngChart.setOption(buildExportOption(instance.lastOption));
    const url = pngChart.getDataURL({
      type: "png",
      pixelRatio: 2,
      backgroundColor: "#fff",
    });
    const link = document.createElement("a");
    link.href = url;
    link.download = (datasetName || "chart") + ".png";
    link.click();
  } finally {
    pngChart.dispose();
  }
}

function noDataOption(message) {
  return {
    title: {
      text: message || "No data to show for this time range",
      left: "center",
      top: "middle",
      textStyle: { fontWeight: "normal", color: "#888" },
    },
  };
}

// Tooltip matching the Vega-Lite charts: a two-column table per data point
// Render the rich single-point table for one series' data point.
function singlePointTooltip(meta, value) {
  if (!meta || !value) {
    return "";
  }
  return tooltipTable([
    ["Sensor", meta.sensorDescription],
    [capFirst(meta.sensorType), formatQuantity(value[1], meta.unit)],
    ["Time and date", formatFullDate(value[0])],
    ["Horizon", formatTimedelta(value[2])],
    ["Source", meta.source.name + " (ID: " + meta.source.id + ")"],
    ["Type", meta.source.display_type || ""],
    ["Model", meta.source.model || ""],
    ["Version", meta.source.version || ""],
  ]);
}

function seriesTooltipFormatter(seriesMeta) {
  return function (params) {
    // Axis trigger passes an array of the series' points near the ruler; item
    // trigger passes a single point. In both cases we show just the nearest one,
    // as in the Vega-Lite charts (which snap to the nearest data point on hover).
    if (Array.isArray(params)) {
      if (params.length === 0) {
        return "";
      }
      // Pick the point closest to the ruler position (params[i].axisValue).
      const ref = params[0].axisValue;
      let best = params[0];
      let bestDist = Infinity;
      for (const p of params) {
        const x = p.value && p.value[0];
        const dist = typeof x === "number" && typeof ref === "number" ? Math.abs(x - ref) : 0;
        if (dist < bestDist) {
          bestDist = dist;
          best = p;
        }
      }
      return singlePointTooltip(seriesMeta[best.seriesIndex], best.value);
    }
    if (params.componentType === "legend") {
      return escapeHtml(params.name); // legend hover: just reveal the full series name
    }
    return singlePointTooltip(seriesMeta[params.seriesIndex], params.value);
  };
}

/* ============================== annotations ============================== */

// Parse the annotation records (start, end, content) fetched for the sensor page
// into sorted {start, end, label} entries with epoch-ms bounds.
function normalizeAnnotations(raw) {
  if (!Array.isArray(raw) || raw.length === 0) return [];
  return raw
    .map((a) => ({
      start: new Date(a.start).getTime(),
      end: new Date(a.end).getTime(),
      label: Array.isArray(a.content) ? a.content.join("\n") : (a.content || ""),
    }))
    .filter((a) => isFinite(a.start) && isFinite(a.end))
    .sort((a, b) => a.start - b.start);
}

// Build the markArea config for the annotation shades. The band at hoverIdx is
// highlighted (secondary-hover color, label shown); the rest are gray at 0.3 opacity,
// matching Vega-Lite's SHADE_LAYER (default --gray) and TEXT_LAYER (label on hover).
function buildAnnotationMarkArea(annotations, hoverIdx) {
  const cs = getComputedStyle(document.documentElement);
  const grayColor = cs.getPropertyValue("--gray").trim() || "#bbb";
  const hoverColor = cs.getPropertyValue("--secondary-hover-color").trim() || "#f5a623";
  return {
    silent: true, // hover is handled via the updateAxisPointer listener instead
    animation: false,
    data: annotations.map((a, idx) => {
      const hovered = idx === hoverIdx;
      return [
        {
          xAxis: a.start,
          itemStyle: { color: hovered ? hoverColor : grayColor, opacity: hovered ? 0.7 : 0.3 },
          label: {
            show: hovered,
            position: ["50%", "100%"], // centered, at the bottom of the band
            offset: [0, 34], // push below the x-axis labels, like Vega's text layer
            align: "center",
            verticalAlign: "top",
            fontSize: FONT_SIZE,
            fontStyle: "italic",
            color: "#333",
            formatter: () => a.label,
          },
        },
        { xAxis: a.end },
      ];
    }),
  };
}

/* ============================== line / bar charts ============================== */

function buildLineBarOption(elementId, groups, opts) {
  const instance = instances[elementId];
  const container = document.getElementById(elementId);
  const annotations = normalizeAnnotations(opts.annotations);
  // Sensor page: legend always below (single sensor, sources are the legend entries)
  const legendsBelow = !!opts.legendsBelow || opts.isSensorPage;
  const gridGap = SIDE_GRID_GAP;
  const gridRight = legendsBelow ? 30 : LEGEND_WIDTH + 40;
  const containerWidth = container.clientWidth || 800;
  const plotCenter = (GRID_LEFT + containerWidth - gridRight) / 2;

  // The Source key is only shown when multiple source types are actually present,
  // matching Vega-Lite which only adds the strokeDash legend when needed.
  const allSourceTypes = new Set(
    groups.flatMap((g) => g.series.map((s) => lineTypeForSource(s.source)))
  );
  const showSourceKey = opts.chartType !== "bar_chart" && groups[0].nameBySensor && allSourceTypes.size > 1;
  const topOffset = TOP_OFFSET;

  // Vertical layout: subplots, then (in legends-below mode) the slider and
  // one combined legend at the very bottom, as in the Vega-Lite charts
  const lastGridBottom =
    topOffset + groups.length * GRID_HEIGHT + (groups.length - 1) * gridGap;
  // Bottom legend: stack vertically (one entry per row) when there are many
  // entries (asset charts with several sensors), as in the Vega-Lite charts;
  // keep it horizontal for a few entries (e.g. the sensor page's sources).
  const numLegendEntries = new Set(
    groups.flatMap((g) => g.series.map((s) => s.name))
  ).size;
  const bottomLegendVertical = numLegendEntries > 4;
  const itemsPerRow = Math.max(Math.floor((containerWidth - GRID_LEFT - 30) / 220), 1);
  const legendHeight = bottomLegendVertical
    ? numLegendEntries * 24 + 8
    : Math.ceil(numLegendEntries / itemsPerRow) * 24 + 8;
  // Reserve a strip below the x-axis labels for the hovered annotation's name.
  const annotGap = annotations.length > 0 ? 28 : 0;
  const legendZoneTop = lastGridBottom + 36 + annotGap;
  const bottomLegendTitleTop = legendZoneTop + 14; // "Source"/"Sensor" heading
  const legendTitleHeight = 24;
  const bottomLegendTop = bottomLegendTitleTop + legendTitleHeight;

  // The "Source" line-style key placement, matching the Vega-Lite charts:
  // - side-legend layout: bottom-left, below the last subplot's x-axis labels.
  // - legends-below layout: a second column to the right of, and top-aligned
  //   with, the "Sensor" legend (not stacked below it).
  const sourceKeyLeft = legendsBelow ? GRID_LEFT + 400 : GRID_LEFT;
  const sourceKeyTop = legendsBelow
    ? bottomLegendTitleTop
    : lastGridBottom + 44;

  // The container is a ".card" with vertical padding; under border-box sizing
  // that padding shrinks the usable canvas, which would clip the bottom legend
  // on short single-plot (sensor-page) charts. Add it back so nothing is cut off.
  const cs = window.getComputedStyle(container);
  const verticalPadding =
    (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
  // The bottom zone must fit whichever is taller: the Sensor legend column or
  // the (side-by-side) Source key column.
  const bottomLegendBottom = Math.max(
    bottomLegendTop + legendHeight + 12,
    showSourceKey && legendsBelow ? sourceKeyTop + SOURCE_KEY_HEIGHT + 12 : 0
  );
  container.style.height = legendsBelow
    ? bottomLegendBottom + verticalPadding + "px"
    : topOffset + groups.length * (GRID_HEIGHT + gridGap) + BOTTOM_OFFSET + verticalPadding + "px";

  const grids = [];
  const xAxes = [];
  const yAxes = [];
  const titles = [];
  const legends = [];
  const series = [];
  const seriesMeta = [];
  const sensorColor = new Map();

  // Share one x domain across all subplots, as Vega-Lite does (resolve.scale.x =
  // "shared"), so the time axes stay aligned even when some subplots' data (e.g.
  // fixed-value lines spanning the full window) reach further than others'.
  let sharedMinTime = Infinity;
  let sharedMaxTime = -Infinity;
  groups.forEach((g) =>
    g.series.forEach((s) =>
      s.points.forEach((p) => {
        const x = typeof p[0] === "number" ? p[0] : +new Date(p[0]);
        if (isFinite(x)) {
          if (x < sharedMinTime) sharedMinTime = x;
          if (x > sharedMaxTime) sharedMaxTime = x;
        }
      })
    )
  );
  const sharedXDomain =
    isFinite(sharedMinTime) && isFinite(sharedMaxTime)
      ? { min: sharedMinTime, max: sharedMaxTime }
      : {};

  groups.forEach((group, i) => {
    const top = topOffset + i * (GRID_HEIGHT + gridGap);
    grids.push({
      top: top,
      height: GRID_HEIGHT,
      left: GRID_LEFT,
      right: gridRight,
      containLabel: false,
    });
    titles.push({
      text: group.title,
      left: plotCenter,
      textAlign: "center",
      top: top - 42,
      textStyle: { fontSize: Math.round(FONT_SIZE * 1.25), color: "#222" }, // matches Vega-Lite title size (20 px)
    });
    if (!legendsBelow) {
      const legendNames = Array.from(new Set(group.series.map((s) => s.name)));
      // Vertically center the legend beside its subplot rather than pinning it
      // to the top of the chart. Estimate the rendered height (one row per entry)
      // and offset from the grid top by half the leftover space.
      const rowHeight = FONT_SIZE + 6; // font size + itemGap between rows
      const legendContentHeight = legendNames.length * rowHeight;
      const legendTop = top + Math.max(0, (GRID_HEIGHT - legendContentHeight) / 2);
      legends.push({
        // One vertical legend beside each subplot, listing only its own series
        data: legendNames,
        type: "scroll",
        tooltip: { show: true }, // hover reveals truncated names in full
        orient: "vertical",
        right: 8,
        top: legendTop,
        height: GRID_HEIGHT,
        align: "left",
        itemWidth: 18,
        itemGap: 6,
        textStyle: {
          fontSize: FONT_SIZE,
          // Truncate long names with an ellipsis, e.g. "sensor-007 (bulk...)".
          // The full name is still revealed on hover via the legend tooltip.
          width: LEGEND_WIDTH - 30,
          overflow: "truncate",
        },
      });
    }
    xAxes.push({
      type: "time",
      gridIndex: i,
      ...sharedXDomain, // keep every subplot on the same time domain
      axisLine: { onZero: false },
      axisPointer: { show: true }, // vertical ruler, as in the Vega-Lite charts
      splitLine: { show: true, lineStyle: { opacity: 0.5 } },
      // Finer (hourly) gridlines between the 6-hour major lines, as in Vega-Lite.
      minorTick: { show: true, splitNumber: 6 },
      minorSplitLine: { show: true, lineStyle: { color: "#e0e0e0", width: 1 } },
      minInterval: 6 * 3600 * 1000, // at most one tick per 6h so 12:00 labels appear
      axisLabel: {
        fontSize: FONT_SIZE,
        color: "#222",
        formatter: xAxisTimeFormatter,
      },
    });
    yAxes.push({
      type: "value",
      gridIndex: i,
      name: yAxisTitle(group.sensorType, group.units), // e.g. "Power (kW)"
      nameLocation: "end",
      nameTextStyle: {
        fontSize: FONT_SIZE,
        fontWeight: "bold",
        color: "#222",
        align: "left",
        padding: [0, 0, 4, -GRID_LEFT + 16],
      },
      axisLabel: { fontSize: FONT_SIZE, color: "#222" },
      splitLine: { show: true, lineStyle: { opacity: 0.7 } },
      // Finer gridlines between the major value lines, as in Vega-Lite.
      minorTick: { show: true, splitNumber: 2 },
      minorSplitLine: { show: true, lineStyle: { color: "#e0e0e0", width: 1 } },
    });
    // Match Vega-Lite (chart_for_multiple_sensors): use linear interpolation for
    // the whole row if ANY of its sensors is instantaneous (event_resolution 0),
    // otherwise step-after. Prefer the sensor's real resolution; fall back to
    // inferring it from event spacing only for legacy data without it.
    const groupIsInstantaneous = group.series.some((s) =>
      typeof s.eventResolutionSec === "number"
        ? s.eventResolutionSec === 0
        : inferResolutionMs(s.eventStarts || []) <= 60 * 1000
    );
    group.series.forEach((s, j) => {
      const isBar = opts.chartType === "bar_chart";
      const entry = {
        name: s.name,
        type: isBar ? "bar" : "line",
        xAxisIndex: i,
        yAxisIndex: i,
        data: s.points,
        emphasis: { focus: "series" },
        animation: false,
      };
      // One color per sensor: series of the same sensor share their legend
      // entry's color, and sources are told apart by line style instead
      if (group.nameBySensor) {
        if (!sensorColor.has(s.name)) {
          sensorColor.set(s.name, SENSOR_COLORS[sensorColor.size % SENSOR_COLORS.length]);
        }
        entry.color = sensorColor.get(s.name);
      }
      if (isBar) {
        Object.assign(entry, {
          barGap: "-100%", // overlay sources, as in the Vega-Lite bar chart
          large: true,
          itemStyle: { opacity: 0.7 },
        });
      } else {
        Object.assign(entry, {
          ...(groupIsInstantaneous ? {} : { step: "end" }), // step-after for interval data
          showSymbol: false,
          sampling: "lttb", // downsample to the available pixels, preserving peaks
          large: true, // batched canvas path: faster redraws while panning/zooming
          largeThreshold: 1000,
          lineStyle: { width: 2.2, type: lineTypeForSource(s.source) },
        });
      }
      // Replay ruler: a vertical line at the current belief time
      if (instance.replayTime != null && j === 0) {
        entry.markLine = {
          silent: true,
          symbol: "none",
          animation: false,
          data: [{ xAxis: instance.replayTime }],
          lineStyle: { color: "#555", width: 1.5, type: "solid" },
          label: { show: false },
        };
      }
      // Annotation shades on the first series of each subplot. Gray at 0.3 opacity by
      // default; the zrender mousemove handler in renderFastChart recolors the hovered
      // band and reveals its label, matching Vega-Lite's SHADE_LAYER/TEXT_LAYER.
      if (j === 0 && annotations.length > 0) {
        entry.markArea = buildAnnotationMarkArea(annotations, -1);
      }
      series.push(entry);
      seriesMeta.push(s);
    });
  });

  // Title above the bottom legend: "Sensor" for multi-sensor (asset) charts,
  // "Source" for single-sensor (sensor page) charts, as in the Vega-Lite charts.
  const bottomLegendTitle = legendsBelow
    ? {
        type: "text",
        left: GRID_LEFT,
        top: bottomLegendTitleTop,
        style: {
          text: groups[0].nameBySensor ? "Sensor" : "Source",
          font: "bold " + FONT_SIZE + "px " + CHART_FONT,
          fill: "#222",
        },
      }
    : null;

  if (legendsBelow) {
    // One combined legend below all subplots, stacked vertically (one entry per
    // row) as in the Vega-Lite charts rather than wrapping horizontally.
    legends.push({
      // "plain" (not "scroll"): the container height already grows to fit every
      // entry (see legendHeight), so all entries show without pagination
      // controls that would otherwise eat the space and hide the items.
      data: Array.from(new Set(seriesMeta.map((s) => s.name))),
      type: "plain",
      orient: bottomLegendVertical ? "vertical" : "horizontal",
      left: GRID_LEFT,
      right: bottomLegendVertical ? undefined : 30,
      top: bottomLegendTop,
      itemWidth: 18,
      itemGap: bottomLegendVertical ? 6 : 12,
      textStyle: { fontSize: FONT_SIZE },
      tooltip: { show: true },
    });
  }

  // Source line-style key, as in the Vega-Lite charts' "Source" legend:
  // a vertical column at the bottom-left, below the chart / bottom legend.
  const sourceKey = showSourceKey ? buildSourceKey(sourceKeyLeft, sourceKeyTop) : null;

  const allAxisIndices = xAxes.map((_, i) => i);
  const toolbox = toolboxFeatures(elementId, opts.datasetName, opts.isSensorPage);
  toolbox.feature.dataZoom.xAxisIndex = allAxisIndices;

  return {
    textStyle: { fontFamily: CHART_FONT, fontSize: FONT_SIZE },
    graphic: [sourceKey, bottomLegendTitle].filter(Boolean),
    grid: grids,
    title: titles,
    xAxis: xAxes,
    yAxis: yAxes,
    series: series,
    legend: legends,
    axisPointer: {
      link: [{ xAxisIndex: "all" }], // sync the ruler across subplots
    },
    tooltip: {
      // Axis trigger so hovering anywhere snaps to the nearest data point (the
      // ruler), as in the Vega-Lite charts, instead of requiring a direct hit on
      // the thin line. The formatter then shows just that nearest point.
      trigger: "axis",
      confine: true,
      axisPointer: { type: "line" },
      formatter: seriesTooltipFormatter(seriesMeta),
    },
    toolbox: toolbox,
    dataZoom: [
      // Mouse-wheel zoom and drag-to-pan. throttle coalesces rapid wheel/drag
      // ticks so we redraw at most every ~80 ms instead of on every event.
      { type: "inside", xAxisIndex: allAxisIndices, throttle: 80 },
    ],
  };
}

/* ============================== histogram ============================== */

// Nice bin width (1/2/5 × 10^k), aiming for ~10 bins as Vega-Lite does
function niceBinWidth(span, targetBins) {
  const rawStep = span / targetBins;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
  for (const m of [1, 2, 5, 10]) {
    if (rawStep <= m * magnitude) {
      return m * magnitude;
    }
  }
  return 10 * magnitude;
}

function buildHistogramOption(elementId, data, opts) {
  const rows = numericRows(data);
  if (rows.length === 0) {
    return null;
  }
  const container = document.getElementById(elementId);
  container.style.height = TOP_OFFSET + 400 + BOTTOM_OFFSET + "px";

  const values = rows.map((r) => r.event_value);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const width = niceBinWidth(hi - lo || 1, 10);
  const start = Math.floor(lo / width) * width;
  const numBins = Math.max(Math.ceil((hi - start) / width), 1);
  const unit = rows[0].sensor ? rows[0].sensor.unit || "" : "";
  const sensorType = (opts.groupSpec && opts.groupSpec[0] && opts.groupSpec[0].sensorType) || "";

  // Count values per bin, per source
  const sources = new Map(); // label -> counts array
  for (const row of rows) {
    const label = sourceLabel(row.source || {});
    if (!sources.has(label)) {
      sources.set(label, new Array(numBins).fill(0));
    }
    let bin = Math.floor((row.event_value - start) / width);
    bin = Math.min(Math.max(bin, 0), numBins - 1);
    sources.get(label)[bin] += 1;
  }
  const binLabels = [];
  for (let b = 0; b < numBins; b++) {
    binLabels.push(formatQuantity(start + b * width, "") + " – " + formatQuantity(start + (b + 1) * width, ""));
  }

  const series = [];
  for (const [label, counts] of sources) {
    series.push({
      name: label,
      type: "bar",
      data: counts,
      stack: "counts", // stack sources, as in the Vega-Lite histogram
      barCategoryGap: "0%", // contiguous bins, as in the Vega-Lite histogram
      itemStyle: { opacity: 0.7 },
      animation: false,
    });
  }

  return {
    grid: { top: TOP_OFFSET + 60, height: 320, left: GRID_LEFT, right: opts.legendsBelow ? 30 : LEGEND_WIDTH + 40 },
    series: series,
    xAxis: {
      type: "category",
      data: binLabels,
      position: "top", // bin labels at the top, as in the Vega-Lite histogram
      name: yAxisTitle(sensorType, [unit]),
      nameLocation: "middle",
      nameGap: 40,
      nameTextStyle: { fontSize: FONT_SIZE, fontWeight: "bold", color: "#222" },
      axisLabel: { fontSize: FONT_SIZE },
    },
    yAxis: {
      type: "value",
      name: "Count",
      nameLocation: "end",
      nameTextStyle: { fontSize: FONT_SIZE, fontWeight: "bold", color: "#222", align: "left", padding: [0, 0, 4, -GRID_LEFT + 16] },
      splitLine: { show: true, lineStyle: { opacity: 0.7 } },
    },
    legend: {
      data: Array.from(sources.keys()),
      type: "scroll",
      orient: opts.legendsBelow ? "horizontal" : "vertical",
      right: opts.legendsBelow ? undefined : 8,
      left: opts.legendsBelow ? GRID_LEFT : undefined,
      top: opts.legendsBelow ? TOP_OFFSET + 395 : TOP_OFFSET + 60,
      textStyle: { fontSize: FONT_SIZE },
      tooltip: { show: true },
    },
    tooltip: {
      trigger: "item",
      confine: true,
      formatter: (params) => {
        if (params.componentType === "legend") {
          return escapeHtml(params.name);
        }
        return tooltipTable([
          [capFirst(sensorType || "value") + (unit ? " (" + unit + ")" : ""), binLabels[params.dataIndex]],
          ["Count", params.value],
          ["Source", params.seriesName],
        ]);
      },
    },
    textStyle: { fontFamily: CHART_FONT, fontSize: FONT_SIZE },
    toolbox: toolboxFeatures(elementId, opts.datasetName, opts.isSensorPage),
  };
}

/* ============================== heatmaps ============================== */

function buildHeatmapOption(elementId, data, opts) {
  const split = opts.chartType === "weekly_heatmap" ? "weekly" : "daily";
  const rows = mostPrevalentSourceRows(numericRows(data));
  if (rows.length === 0) {
    return null;
  }
  const resMs = inferResolutionMs(rows);
  const slotsPerDay = Math.max(Math.round((24 * 60 * 60 * 1000) / resMs), 1);
  const numSlots = split === "daily" ? slotsPerDay : 7 * slotsPerDay;
  const unit = rows[0].sensor ? rows[0].sensor.unit || "" : "";
  const sensorType = (opts.groupSpec && opts.groupSpec[0] && opts.groupSpec[0].sensorType) || "";
  const source = rows[0].source || {};

  // y categories: one row per day (daily) or per week starting Sunday (weekly)
  const yKey = (d) => {
    const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    if (split === "weekly") {
      day.setDate(day.getDate() - day.getDay()); // back to Sunday
    }
    return day.getTime();
  };
  const yKeys = Array.from(new Set(rows.map((r) => yKey(new Date(r.event_start))))).sort((a, b) => a - b);
  const yIndex = new Map(yKeys.map((k, i) => [k, i]));

  const cells = [];
  let minVal = 0;
  let maxVal = 0;
  for (const row of rows) {
    const d = new Date(row.event_start);
    const minutesOfDay = d.getHours() * 60 + d.getMinutes();
    const slotOfDay = Math.floor((minutesOfDay * 60 * 1000) / resMs);
    const x = split === "daily" ? slotOfDay : d.getDay() * slotsPerDay + slotOfDay;
    const y = yIndex.get(yKey(d));
    cells.push({ value: [x, y, row.event_value], row: row });
    minVal = Math.min(minVal, row.event_value);
    maxVal = Math.max(maxVal, row.event_value);
  }
  // Symmetric range so that 0 sits at the white center of the diverging scale
  const absMax = Math.max(Math.abs(minVal), Math.abs(maxVal)) || 1;

  const xLabels = [];
  for (let i = 0; i < numSlots; i++) {
    if (split === "daily") {
      const minutes = Math.round((i * resMs) / 60000);
      xLabels.push(String(Math.floor(minutes / 60)).padStart(2, "0") + ":" + String(minutes % 60).padStart(2, "0"));
    } else {
      xLabels.push(DAY_NAMES[Math.floor(i / slotsPerDay)]);
    }
  }
  const labelEvery = split === "daily" ? Math.max(Math.round(slotsPerDay / 12), 1) : slotsPerDay;

  const gridHeight = Math.min(Math.max(yKeys.length * 26, 120), 460);
  const container = document.getElementById(elementId);
  container.style.height = TOP_OFFSET + gridHeight + BOTTOM_OFFSET + 40 + "px";

  return {
    grid: { top: TOP_OFFSET + 20, height: gridHeight, left: 110, right: LEGEND_WIDTH + 40 },
    xAxis: {
      type: "category",
      data: xLabels,
      splitArea: { show: false },
      axisLabel: {
        interval: (idx) => idx % labelEvery === 0,
        fontSize: 10,
      },
    },
    yAxis: {
      type: "category",
      data: yKeys.map(formatDate),
      inverse: true, // earliest at the top, as in the Vega-Lite heatmaps
      name: yAxisTitle(sensorType, [unit]),
      nameLocation: "end",
      nameTextStyle: { fontSize: FONT_SIZE, fontWeight: "bold", color: "#222", align: "left", padding: [0, 0, 4, -94] },
    },
    visualMap: {
      type: "continuous",
      min: -absMax,
      max: absMax,
      calculable: true, // draggable handles to filter the value range
      orient: "vertical",
      right: 30,
      top: TOP_OFFSET + 20,
      inRange: { color: BLUE_ORANGE },
      text: [formatQuantity(absMax, unit), formatQuantity(-absMax, unit)],
      textStyle: { fontSize: 10 },
    },
    tooltip: {
      confine: true,
      formatter: (params) => {
        const row = params.data && params.data.row;
        if (!row) {
          return "";
        }
        return tooltipTable([
          ["Time and date", formatFullDate(row.event_start)],
          [capFirst(sensorType || "value"), formatQuantity(row.event_value, unit)],
          ["Source", source.name + " (ID: " + source.id + ")"],
          ["Model", source.model || ""],
          ["Version", source.version || ""],
        ]);
      },
    },
    textStyle: { fontFamily: CHART_FONT, fontSize: FONT_SIZE },
    toolbox: toolboxFeatures(elementId, opts.datasetName, opts.isSensorPage),
    series: [
      {
        type: "heatmap",
        data: cells,
        emphasis: { itemStyle: { borderColor: "#333", borderWidth: 1 } },
        progressive: 5000,
        animation: false,
      },
    ],
  };
}

/* ============================== charge point sessions ============================== */

// Sensor names that report Charge Point session timestamps (unit "s", the value
// is itself an epoch time). Pivoted per (asset, event_start) into session bars,
// mirroring the Vega-Lite "Charge Point sessions" chart's arrival/departure,
// plug-in/plug-out and start/stop-charging layers.
const SESSION_SENSOR_NAMES = [
  "arrival", "departure", "plug in", "plug out", "start charging", "stop charging",
];

// Pivot session-marker rows into one record per (asset, session): each holds up
// to three timestamp pairs (in ms) reported for that session. Rows for the same
// session share both their asset and their event_start (the belief time at which
// the session's timestamps were reported), which is how Vega-Lite groups them too.
function pivotChargePointSessions(data) {
  const groups = new Map();
  for (const row of data || []) {
    const sensor = row.sensor || {};
    if (sensor.unit !== "s" || !SESSION_SENSOR_NAMES.includes(sensor.name)) {
      continue;
    }
    const ms = row.event_value instanceof Date ? row.event_value.getTime() : row.event_value;
    if (typeof ms !== "number" || !isFinite(ms) || ms <= 0) {
      continue;
    }
    const assetId = sensor.asset_id;
    const key = assetId + "_" + row.event_start;
    if (!groups.has(key)) {
      groups.set(key, {
        assetId: assetId,
        assetLabel: sensor.asset_description || "Asset " + assetId,
      });
    }
    groups.get(key)[sensor.name] = ms;
  }
  return Array.from(groups.values());
}

// Distinguish charge point assets that share the same description, mirroring
// computeSourceLabels: unique descriptions are shown as-is, duplicates get their id appended.
function computeAssetLabels(sessions) {
  const byId = new Map();
  for (const s of sessions) {
    if (!byId.has(s.assetId)) byId.set(s.assetId, s.assetLabel);
  }
  const nameCount = new Map();
  for (const label of byId.values()) {
    nameCount.set(label, (nameCount.get(label) || 0) + 1);
  }
  const labels = new Map();
  for (const [id, label] of byId) {
    labels.set(id, nameCount.get(label) === 1 ? label : label + " (ID: " + id + ")");
  }
  return labels;
}

// Build one real "line" series per session segment (2 points: from -> to on the
// asset's category row), named by asset so ECharts' native legend groups every
// layer of the same asset under one clickable, color-coded entry — matching
// Vega-Lite's per-asset color legend and its "click legend to filter" behavior.
function buildSessionSegmentSeries(sessions, fromKey, toKey, categoryIndex, lineWidth, lineDash, fromLabel, toLabel) {
  const series = [];
  for (const s of sessions) {
    const from = s[fromKey];
    const to = s[toKey];
    if (typeof from !== "number" || typeof to !== "number") continue;
    const catIdx = categoryIndex.get(s.assetId);
    const color = SENSOR_COLORS[catIdx % SENSOR_COLORS.length];
    const data = [[from, catIdx], [to, catIdx]];
    const tooltip = {
      formatter: () =>
        tooltipTable([
          [fromLabel, formatFullDate(from)],
          [toLabel, formatFullDate(to)],
          ["Asset", s.assetLabel],
        ]),
    };
    // Regular time-series lines (e.g. the companion subplots) have a data point
    // every few pixels, so ECharts' "nearest point" hover snap always finds one
    // close to the cursor anywhere along the line. A session segment only has 2
    // points — its start and end, often hours apart — so that snap logic finds
    // nothing nearby over most of a long bar. Densely interpolate the invisible
    // hit-area line (kept off the visible line) so hovering anywhere along the
    // bar's length has a point within range, not just right at its endpoints.
    const hitPointCount = 40;
    const hitData = [];
    for (let i = 0; i <= hitPointCount; i++) {
      hitData.push([from + ((to - from) * i) / hitPointCount, catIdx]);
    }
    // Invisible companion line, much wider than the visible stroke, purely to
    // widen the hoverable hit area: thin session bars (down to 1.5px) are
    // otherwise very hard to hover precisely. Shares the visible line's name
    // so it doesn't add its own legend entry or get toggled independently.
    // Its OWN tooltip is disabled (tooltip.show: false): ECharts' tooltip box
    // renders at zero size for a near-transparent series even though hover/hit
    // -test work fine on it, so hovering it instead redirects (via the
    // __hitAreaFor marker + the mouseover listener in wireSessionTooltipRedirect)
    // to dispatch the visible sibling series' tooltip.
    series.push({
      name: s.assetLabel,
      type: "line",
      xAxisIndex: 0,
      yAxisIndex: 0,
      symbol: "none",
      showSymbol: false,
      animation: false,
      legendHoverLink: false,
      lineStyle: { width: Math.max(lineWidth, 16), opacity: 0.001 },
      data: hitData,
      tooltip: { show: false },
      __hitAreaFor: true,
      z: 1,
    });
    series.push({
      name: s.assetLabel,
      type: "line",
      xAxisIndex: 0,
      yAxisIndex: 0,
      symbol: "none",
      showSymbol: false,
      animation: false,
      color: color,
      lineStyle: { width: lineWidth, type: lineDash || "solid" },
      emphasis: { focus: "series", lineStyle: { width: lineWidth + 2 } },
      data: data,
      tooltip: tooltip,
      z: 2,
    });
  }
  return series;
}

// The two companion subplots Vega-Lite shows alongside the sessions chart (when
// present in the dashboard config), restricted the same way the Python chart
// builder restricts them (see chart_for_chargepoint_sessions in belief_charts.py).
const CHARGEPOINT_COMPANION_TITLES = ["Power flow by type", "Prices"];
const CHARGEPOINT_POWER_SENSOR_NAME = "charge points power";
// Title of the dashboard group holding the raw session-marker sensors (arrival,
// departure, plug in/out, start/stop charging). Their values are epoch timestamps,
// not plottable quantities, so — like Vega-Lite — only the dedicated Charge Point
// sessions chart type shows them; the default multi-sensor view hides this group.
const CHARGE_POINT_SESSIONS_GROUP_TITLE = "Charge Point sessions";

function buildChargePointSessionsOption(elementId, data, opts) {
  const sessions = pivotChargePointSessions(data);
  if (sessions.length === 0) {
    return null;
  }
  const assetLabels = computeAssetLabels(sessions);
  for (const s of sessions) {
    s.assetLabel = assetLabels.get(s.assetId);
  }

  // y categories: one row per charge point asset, in order of first appearance
  const categoryOrder = [];
  const categoryIndex = new Map();
  for (const s of sessions) {
    if (!categoryIndex.has(s.assetId)) {
      categoryIndex.set(s.assetId, categoryOrder.length);
      categoryOrder.push(s.assetLabel);
    }
  }

  const sessionSeries = [
    ...buildSessionSegmentSeries(sessions, "arrival", "departure", categoryIndex, 1.5, "dashed", "Arrival", "Departure"),
    ...buildSessionSegmentSeries(sessions, "plug in", "plug out", categoryIndex, 2.5, "solid", "Plug-in", "Plug-out"),
    ...buildSessionSegmentSeries(sessions, "start charging", "stop charging", categoryIndex, 6, "solid", "Start charging", "Stop charging"),
  ];

  // Same two companion subplots Vega-Lite stacks below the sessions chart, built
  // via the normal multi-sensor line-chart renderer and spliced in underneath.
  const companionSpec = (opts.groupSpec || []).filter((g) => CHARGEPOINT_COMPANION_TITLES.includes(g.title));
  let companionGroups = companionSpec.length > 0 ? groupData(data, companionSpec) : [];
  // groupData() falls back to grouping any row not covered by companionSpec's
  // sensorIds by unit, producing extra ad-hoc groups for the asset's other
  // sensors (soc, power, ...) — drop everything except the two intended titles.
  companionGroups = companionGroups
    .filter((g) => CHARGEPOINT_COMPANION_TITLES.includes(g.title))
    .map((g) =>
      g.title === "Power flow by type"
        ? Object.assign({}, g, { series: g.series.filter((s) => s.sensorName === CHARGEPOINT_POWER_SENSOR_NAME) })
        : g
    )
    .filter((g) => g.series.length > 0);

  // Give every subplot's x-axis the same explicit time domain, spanning both the
  // session timestamps (arrival/departure/etc., which can fall outside the belief
  // report window) and the companion sensors' event times. Without this, each
  // "time" axis auto-scales to its own series' range independently, so the same
  // clock time lands at a different x position in each subplot — unlike Vega-Lite,
  // which shares one scale across all layered/concatenated charts.
  let minTime = Infinity;
  let maxTime = -Infinity;
  for (const row of data || []) {
    if (typeof row.event_start === "number") {
      if (row.event_start < minTime) minTime = row.event_start;
      if (row.event_start > maxTime) maxTime = row.event_start;
    }
  }
  for (const s of sessions) {
    for (const key of SESSION_SENSOR_NAMES) {
      const t = s[key];
      if (typeof t === "number") {
        if (t < minTime) minTime = t;
        if (t > maxTime) maxTime = t;
      }
    }
  }
  const sharedTimeDomain = isFinite(minTime) && isFinite(maxTime) ? { min: minTime, max: maxTime } : {};

  const container = document.getElementById(elementId);
  const gridGap = SIDE_GRID_GAP;
  const containerWidth = container.clientWidth || 800;
  const plotCenter = (GRID_LEFT + containerWidth - 30) / 2;

  const sessionsTop = TOP_OFFSET;
  const sessionsGridHeight = Math.min(Math.max(categoryOrder.length * 32, 160), 460);
  const sessionsBottom = sessionsTop + sessionsGridHeight;

  // Side legend of asset colors, one entry per asset, matching the per-subplot
  // side legend style used by the other charts; clicking an entry toggles every
  // layer of that asset (they all share its name), just like Vega-Lite.
  const legendRowHeight = FONT_SIZE + 6;
  const legendContentHeight = categoryOrder.length * legendRowHeight;
  const legendTop = sessionsTop + Math.max(0, (sessionsGridHeight - legendContentHeight) / 2);

  const grids = [{ top: sessionsTop, height: sessionsGridHeight, left: GRID_LEFT, right: LEGEND_WIDTH + 40, containLabel: false }];
  const xAxes = [Object.assign({
    type: "time",
    gridIndex: 0,
    axisLine: { onZero: false },
    axisPointer: { show: true },
    splitLine: { show: true, lineStyle: { opacity: 0.5 } },
    minorTick: { show: true, splitNumber: 6 },
    minorSplitLine: { show: true, lineStyle: { color: "#e0e0e0", width: 1 } },
    minInterval: 6 * 3600 * 1000,
    axisLabel: { fontSize: FONT_SIZE, color: "#222", formatter: xAxisTimeFormatter },
  }, sharedTimeDomain)];
  const yAxes = [{
    type: "category",
    gridIndex: 0,
    data: categoryOrder,
    name: "Sessions",
    nameLocation: "end",
    nameTextStyle: { fontSize: FONT_SIZE, fontWeight: "bold", color: "#222", align: "left", padding: [0, 0, 4, -GRID_LEFT + 16] },
    axisLabel: { show: false },
    axisTick: { show: false },
    splitLine: { show: false },
  }];
  const titles = [{
    text: "Charge Point sessions",
    left: plotCenter,
    textAlign: "center",
    top: sessionsTop - 42,
    textStyle: { fontSize: Math.round(FONT_SIZE * 1.25), color: "#222" },
  }];
  const legends = [{
    data: categoryOrder,
    type: "scroll",
    tooltip: { show: true },
    orient: "vertical",
    right: 8,
    top: legendTop,
    height: sessionsGridHeight,
    align: "left",
    itemWidth: 18,
    itemGap: 6,
    textStyle: { fontSize: FONT_SIZE, width: LEGEND_WIDTH - 30, overflow: "truncate" },
  }];
  const graphics = [
    { type: "text", left: containerWidth - LEGEND_WIDTH, top: sessionsTop - 20, style: { text: "Asset", font: "bold " + FONT_SIZE + "px " + CHART_FONT, fill: "#222" } },
  ];
  const series = sessionSeries.slice();
  // Aligned 1:1 with the final `series` array: null for the session segment
  // series (they carry their own per-series tooltip), real metadata for the
  // companion series, which rely on the shared seriesTooltipFormatter below.
  const seriesMeta = new Array(sessionSeries.length).fill(null);

  // Splice the companion subplots (each built independently by the normal
  // line-chart renderer, one group at a time so its own Source key — e.g. for
  // Prices' forecaster/scheduler/other sources — lands right above its own
  // subplot instead of a single misplaced key shared across both) in below the
  // sessions chart, re-indexed onto the shared grid/axis/dataZoom set.
  let runningTop = sessionsBottom + gridGap;
  let indexShift = 1;
  companionGroups.forEach((group) => {
    const companionOption = buildLineBarOption(elementId, [group], Object.assign({}, opts, {
      chartType: "line",
      legendsBelow: false,
      isSensorPage: false,
      annotations: [],
    }));
    const deltaTop = runningTop - companionOption.grid[0].top;
    const shiftedTop = runningTop; // capture before the mutations below shift grid[0].top in place
    companionOption.grid.forEach((g) => { g.top += deltaTop; grids.push(g); });
    companionOption.title.forEach((t) => { t.top += deltaTop; titles.push(t); });
    companionOption.xAxis.forEach((x) => { x.gridIndex = indexShift; Object.assign(x, sharedTimeDomain); xAxes.push(x); });
    companionOption.yAxis.forEach((y) => { y.gridIndex = indexShift; yAxes.push(y); });
    companionOption.series.forEach((s) => {
      s.xAxisIndex = indexShift;
      s.yAxisIndex = indexShift;
      series.push(s);
    });
    seriesMeta.push(...group.series);
    companionOption.legend.forEach((l) => { if (typeof l.top === "number") l.top += deltaTop; legends.push(l); });
    (companionOption.graphic || []).forEach((g) => { if (g && typeof g.top === "number") g.top += deltaTop; if (g) graphics.push(g); });
    // This subplot's own Source key (when present) now sits below its x-axis
    // labels, so reserve an extra SOURCE_KEY_HEIGHT strip before the next subplot
    // to keep it clear. Subplots without a Source key need no extra room.
    const hasSourceKey = (companionOption.graphic || []).some((g) => g && g.type === "group");
    runningTop = shiftedTop + GRID_HEIGHT + gridGap + (hasSourceKey ? SOURCE_KEY_HEIGHT + 12 : 0);
    indexShift += 1;
  });
  const bottomOffset = companionGroups.length > 0
    ? runningTop - gridGap + BOTTOM_OFFSET
    : sessionsBottom + BOTTOM_OFFSET;

  const cs = window.getComputedStyle(container);
  const verticalPadding = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
  container.style.height = bottomOffset + verticalPadding + "px";

  const allAxisIndices = xAxes.map((_, i) => i);
  const toolbox = toolboxFeatures(elementId, opts.datasetName, opts.isSensorPage);
  toolbox.feature.dataZoom.xAxisIndex = allAxisIndices;

  return {
    textStyle: { fontFamily: CHART_FONT, fontSize: FONT_SIZE },
    graphic: graphics,
    grid: grids,
    title: titles,
    xAxis: xAxes,
    yAxis: yAxes,
    series: series,
    legend: legends,
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    tooltip: {
      trigger: "item",
      confine: true,
      formatter: seriesTooltipFormatter(seriesMeta),
    },
    toolbox: toolbox,
    dataZoom: [
      { type: "inside", xAxisIndex: allAxisIndices, throttle: 80 },
    ],
  };
}

/* ============================== main entry points ============================== */

/**
 * Render (or re-render) the fast chart into the given container element.
 *
 * @param {string} elementId - The id of the container div.
 * @param {Object[]} data - Decompressed chart data rows.
 * @param {Object} [options] - { groupSpec, chartType, legendsBelow, datasetName }.
 *   chartType: "line" (default), "bar_chart", "histogram", "daily_heatmap",
 *   "weekly_heatmap" or "chart_for_chargepoint_sessions".
 */
export function renderFastChart(elementId, data, options) {
  const container = document.getElementById(elementId);
  if (!container || typeof echarts === "undefined") {
    return;
  }
  const opts = options || {};

  let instance = instances[elementId];
  if (!instance || instance.chart.isDisposed()) {
    const chart = echarts.init(container, null, { renderer: "canvas" });
    instance = { chart: chart, resizeTimer: null, lastArgs: null, lastOption: null, replayTime: null };
    // Re-render on resize (debounced), so centered titles stay centered
    instance.onResize = () => {
      clearTimeout(instance.resizeTimer);
      instance.resizeTimer = setTimeout(() => {
        if (!instance.chart.isDisposed() && instance.lastArgs) {
          renderFastChart(elementId, instance.lastArgs.data, instance.lastArgs.options);
        }
      }, 150);
    };
    window.addEventListener("resize", instance.onResize);
    instances[elementId] = instance;
  }
  instance.lastArgs = { data: data, options: options };

  let option;
  if (opts.chartType === "histogram") {
    option = buildHistogramOption(elementId, data, opts);
  } else if (opts.chartType === "daily_heatmap" || opts.chartType === "weekly_heatmap") {
    option = buildHeatmapOption(elementId, data, opts);
  } else if (opts.chartType === "chart_for_chargepoint_sessions") {
    option = buildChargePointSessionsOption(elementId, data, opts);
  } else {
    const groupSpec = (opts.groupSpec || []).filter((g) => g.title !== CHARGE_POINT_SESSIONS_GROUP_TITLE);
    const groups = groupData(data, groupSpec);
    option = groups.length > 0 ? buildLineBarOption(elementId, groups, opts) : null;
  }
  if (!option) {
    option = noDataOption();
  }
  instance.lastOption = option;
  instance.chart.resize(); // pick up container size changes before drawing
  instance.chart.setOption(option, { notMerge: true });

  wireAnnotationHover(instance, opts);
  wireSessionTooltipRedirect(instance, opts);
}

// The wide invisible hit-area series added per session segment (see
// buildSessionSegmentSeries) has its own tooltip disabled, because ECharts
// renders a broken zero-size tooltip box for a near-transparent line series
// even though hover/hit-testing on it work fine. Redirect hover on those
// series to dispatch the visible sibling series' (real) tooltip instead.
function wireSessionTooltipRedirect(instance, opts) {
  const chart = instance.chart;
  if (instance.onSessionHitHover) {
    chart.off("mouseover", instance.onSessionHitHover);
    instance.onSessionHitHover = null;
  }
  if (opts.chartType !== "chart_for_chargepoint_sessions") {
    return;
  }
  instance.onSessionHitHover = (ev) => {
    if (ev.componentType !== "series") return;
    const series = chart.getOption().series || [];
    const hovered = series[ev.seriesIndex];
    if (!hovered || !hovered.__hitAreaFor) return;
    // The visible sibling is always pushed immediately after its hit-area series.
    chart.dispatchAction({ type: "showTip", seriesIndex: ev.seriesIndex + 1, dataIndex: 0 });
  };
  chart.on("mouseover", instance.onSessionHitHover);
}

// Highlight the annotation band under the cursor (color + label), matching Vega-Lite.
// markArea.emphasis does not fire because axisPointer intercepts mouse events, so we
// react to ECharts' updateAxisPointer event (which provides the x-axis value directly)
// and recolor the band that contains it. globalout on the canvas clears the highlight.
function wireAnnotationHover(instance, opts) {
  const annotations = normalizeAnnotations(opts.annotations);
  const chart = instance.chart;
  const zr = chart.getZr();

  // Drop any handlers from a previous render before deciding whether to add new ones.
  if (instance.onAnnotPointer) {
    chart.off("updateAxisPointer", instance.onAnnotPointer);
    zr.off("globalout", instance.onAnnotOut);
    instance.onAnnotPointer = null;
    instance.onAnnotOut = null;
  }
  if (annotations.length === 0) return;

  // The markArea lives on the first series of each subplot; collect their indices.
  const seriesList = chart.getOption().series || [];
  const markAreaSeriesIdx = seriesList.reduce((acc, s, idx) => {
    if (s.markArea) acc.push(idx);
    return acc;
  }, []);
  if (markAreaSeriesIdx.length === 0) return;

  let activeIdx = -1;
  const lastSeriesIdx = markAreaSeriesIdx[markAreaSeriesIdx.length - 1];
  const setHover = (newIdx) => {
    if (newIdx === activeIdx) return;
    activeIdx = newIdx;
    // setOption merges series by position, so build an array up to the last
    // markArea-bearing series; only those carry a new markArea, the rest pass through.
    const seriesPatch = [];
    for (let i = 0; i <= lastSeriesIdx; i++) {
      seriesPatch.push(
        markAreaSeriesIdx.includes(i)
          ? { markArea: buildAnnotationMarkArea(annotations, newIdx) }
          : {}
      );
    }
    chart.setOption({ series: seriesPatch });
  };

  instance.onAnnotPointer = (ev) => {
    const axisInfo = (ev.axesInfo || []).find((a) => a.axisDim === "x") || (ev.axesInfo || [])[0];
    if (!axisInfo) { setHover(-1); return; }
    const xVal = axisInfo.value;
    setHover(annotations.findIndex((a) => xVal >= a.start && xVal <= a.end));
  };
  instance.onAnnotOut = () => setHover(-1);
  chart.on("updateAxisPointer", instance.onAnnotPointer);
  zr.on("globalout", instance.onAnnotOut);
}

/**
 * Set (or clear, with null) the replay belief time, shown as a vertical ruler.
 * Takes effect on the next renderFastChart call.
 */
export function setFastChartReplayTime(elementId, beliefTimeMs) {
  const instance = instances[elementId];
  if (instance) {
    instance.replayTime = beliefTimeMs;
  }
}

/**
 * Dispose the fast chart instance for the given container, freeing its canvas.
 *
 * @param {string} elementId - The id of the container div.
 */
export function disposeFastChart(elementId) {
  const instance = instances[elementId];
  if (instance) {
    window.removeEventListener("resize", instance.onResize);
    clearTimeout(instance.resizeTimer);
    if (!instance.chart.isDisposed()) {
      instance.chart.dispose();
    }
  }
  delete instances[elementId];
}
