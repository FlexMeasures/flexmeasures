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
// group laid out as a single horizontal strip. Reserve SOURCE_KEY_HEIGHT for it.
const SOURCE_KEY_HEIGHT = 22;

function buildSourceKey(left, top) {
  const children = [
    {
      type: "text",
      left: 0,
      top: 3,
      style: { text: "Source", font: "bold 12px sans-serif", fill: "#222" },
    },
  ];
  let x = 56;
  for (const row of SOURCE_KEY_ROWS) {
    children.push({
      type: "line",
      shape: { x1: x, y1: 9, x2: x + 26, y2: 9 },
      style: { stroke: "#555", lineWidth: 1.5, lineDash: row.dash || null },
    });
    children.push({
      type: "text",
      left: x + 32,
      top: 3,
      style: { text: row.label, fontSize: 11, fill: "#222" },
    });
    x += 32 + row.label.length * 6.5 + 22;
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

function toolboxFeatures(elementId, datasetName) {
  return {
    right: 16,
    feature: {
      dataZoom: { yAxisIndex: false },
      mySavePNG: {
        show: true,
        title: "Save as PNG",
        icon: "path://M4 5 L20 5 L20 19 L4 19 Z M8 14 L11 10 L13 13 L15 11 L18 15 L8 15 Z",
        onclick: () => exportPNG(elementId, datasetName),
      },
      mySaveCSV: {
        show: true,
        title: "Save as CSV",
        icon: "path://M5 2 L13 2 L17 6 L17 20 L5 20 Z M7 11 L15 11 M7 14 L15 14 M7 17 L15 17",
        onclick: () => exportCSV(elementId, datasetName),
      },
      mySaveSVG: {
        show: true,
        title: "Save as SVG",
        icon: "path://M5 2 L13 2 L17 6 L17 20 L5 20 Z M7 12 L11 17 L15 9",
        onclick: () => exportSVG(elementId, datasetName),
      },
    },
  };
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
  return Object.assign({}, lastOption, {
    animation: false,
    backgroundColor: "#fff",
    toolbox: { show: false },
    legend: legend,
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
function seriesTooltipFormatter(seriesMeta) {
  return function (params) {
    if (params.componentType === "legend") {
      return escapeHtml(params.name); // legend hover: just reveal the full series name
    }
    const meta = seriesMeta[params.seriesIndex];
    if (!meta) {
      return "";
    }
    const value = params.value;
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
  const topOffset = TOP_OFFSET + (showSourceKey ? SOURCE_KEY_HEIGHT : 0);

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
  const sliderTop = lastGridBottom + 36 + annotGap;
  const bottomLegendTitleTop = sliderTop + 28 + 14; // "Source"/"Sensor" heading
  const legendTitleHeight = 24;
  const bottomLegendTop = bottomLegendTitleTop + legendTitleHeight;

  // The container is a ".card" with vertical padding; under border-box sizing
  // that padding shrinks the usable canvas, which would clip the bottom legend
  // on short single-plot (sensor-page) charts. Add it back so nothing is cut off.
  const cs = window.getComputedStyle(container);
  const verticalPadding =
    (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
  container.style.height = legendsBelow
    ? bottomLegendTop + legendHeight + 12 + verticalPadding + "px"
    : topOffset + groups.length * (GRID_HEIGHT + gridGap) + BOTTOM_OFFSET + verticalPadding + "px";

  const grids = [];
  const xAxes = [];
  const yAxes = [];
  const titles = [];
  const legends = [];
  const series = [];
  const seriesMeta = [];
  const sensorColor = new Map();

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
        formatter: (value) => {
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
        },
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
        // Match Vega-Lite: use step-after for sensors with a fixed event duration
        // (resolution > 0), and linear for instantaneous sensors (resolution ≈ 0)
        // so that ramps / gradual curves are visible, just as in the old charts.
        const seriesResMs = inferResolutionMs(s.eventStarts || []);
        const isInstantaneous = seriesResMs <= 60 * 1000; // ≤ 1 min → treat as instantaneous
        Object.assign(entry, {
          ...(isInstantaneous ? {} : { step: "end" }), // step-after for interval data
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

  // Source line-style key, as in the Vega-Lite charts' "Source" legend.
  // Always shown (all three types) on the sensor-colored line charts, in the
  // strip reserved at the top-left, clear of the toolbox and the side legends.
  const sourceKey = showSourceKey ? buildSourceKey(GRID_LEFT, 6) : null;

  const allAxisIndices = xAxes.map((_, i) => i);
  const toolbox = toolboxFeatures(elementId, opts.datasetName);
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
      trigger: "item", // per-point details, as in the Vega-Lite charts
      confine: true,
      formatter: seriesTooltipFormatter(seriesMeta),
    },
    toolbox: toolbox,
    dataZoom: [
      // Mouse-wheel zoom and drag-to-pan. throttle coalesces rapid wheel/drag
      // ticks so we redraw at most every ~80 ms instead of on every event.
      { type: "inside", xAxisIndex: allAxisIndices, throttle: 80 },
      // Range slider: realtime:false redraws only on drag-release (no mid-drag
      // re-render of all series); a light gray ghost shows the pending window.
      legendsBelow
        ? { type: "slider", xAxisIndex: allAxisIndices, top: sliderTop, height: 28, realtime: false, throttle: 80 }
        : { type: "slider", xAxisIndex: allAxisIndices, bottom: 14, height: 28, realtime: false, throttle: 80 },
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
    toolbox: toolboxFeatures(elementId, opts.datasetName),
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
    toolbox: toolboxFeatures(elementId, opts.datasetName),
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

/* ============================== main entry points ============================== */

/**
 * Render (or re-render) the fast chart into the given container element.
 *
 * @param {string} elementId - The id of the container div.
 * @param {Object[]} data - Decompressed chart data rows.
 * @param {Object} [options] - { groupSpec, chartType, legendsBelow, datasetName }.
 *   chartType: "line" (default), "bar_chart", "histogram", "daily_heatmap" or "weekly_heatmap".
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
  } else {
    const groups = groupData(data, opts.groupSpec);
    option = groups.length > 0 ? buildLineBarOption(elementId, groups, opts) : null;
  }
  if (!option) {
    option = noDataOption();
  }
  instance.lastOption = option;
  instance.chart.resize(); // pick up container size changes before drawing
  instance.chart.setOption(option, { notMerge: true });

  wireAnnotationHover(instance, opts);
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
