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

const GRID_HEIGHT = 220; // height of each subplot in px
const SIDE_GRID_GAP = 56; // vertical space between subplots (axis labels + titles)
const TOP_OFFSET = 48; // room for the toolbox and the first subplot title
const BOTTOM_OFFSET = 78; // room for the slider and the last x-axis labels
const GRID_LEFT = 70; // room for the y-axis labels
const LEGEND_WIDTH = 190; // width of the legend column beside each subplot

// Diverging color scale approximating Vega's "blueorange" scheme (centered at 0)
const BLUE_ORANGE = ["#2166ac", "#67a9cf", "#d1e5f0", "#f7f7f7", "#fee0b6", "#f1a340", "#b35806"];

// One chart instance per container element
const instances = {};

/* ============================== formatting ============================== */

function sourceLabel(source) {
  if (source.description) {
    return source.description;
  }
  let label = source.name || "source " + source.id;
  if (source.model) {
    label += " (" + source.model + ")";
  }
  return label;
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
      });
    }
    // Third dimension carries the belief horizon (ms) for the tooltip;
    // LTTB sampling selects original points, so it survives downsampling.
    group.series
      .get(seriesKey)
      .points.push([row.event_start, row.event_value, row.belief_horizon]);
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

  return groups.map((group) => {
    const series = [];
    for (const s of group.series.values()) {
      s.points.sort((a, b) => a[0] - b[0]);
      // Series sharing a name (same sensor, several sources) toggle together
      // via their shared legend entry, as in the Vega-Lite charts.
      s.name = nameBySensor ? s.sensorDescription || s.sensorName : s.sourceLabel;
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
const SENSOR_COLORS = [
  "#1f77b4", "#ff7f0e", "#d62728", "#76b7b2", "#2ca02c",
  "#bcbd22", "#9467bd", "#f7b6d2", "#8c564b", "#c7c7c7",
  "#17becf", "#e377c2", "#aec7e8", "#ffbb78", "#98df8a",
  "#ff9896", "#c5b0d5", "#c49c94", "#dbdb8d", "#9edae5",
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

// Smallest positive gap between consecutive event starts (the sensor resolution)
function inferResolutionMs(rows) {
  const starts = Array.from(new Set(rows.map((r) => r.event_start))).sort((a, b) => a - b);
  let res = Infinity;
  for (let i = 1; i < starts.length; i++) {
    const gap = starts[i] - starts[i - 1];
    if (gap > 0 && gap < res) {
      res = gap;
    }
  }
  if (!isFinite(res)) {
    res = 60 * 60 * 1000;
  }
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
      restore: {},
      saveAsImage: { name: datasetName || "flexmeasures-chart", title: "Save as PNG" },
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
    svgChart.setOption(Object.assign({}, instance.lastOption, { animation: false, backgroundColor: "#fff" }));
    downloadBlob(svgChart.renderToSVGString(), "image/svg+xml", (datasetName || "chart") + ".svg");
  } finally {
    svgChart.dispose();
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

/* ============================== line / bar charts ============================== */

function buildLineBarOption(elementId, groups, opts) {
  const instance = instances[elementId];
  const container = document.getElementById(elementId);
  const legendsBelow = !!opts.legendsBelow;
  const gridGap = SIDE_GRID_GAP;
  const gridRight = legendsBelow ? 30 : LEGEND_WIDTH + 40;
  const containerWidth = container.clientWidth || 800;
  const plotCenter = (GRID_LEFT + containerWidth - gridRight) / 2;

  // The Source key (line-style legend) is shown on sensor-colored line charts,
  // where sources are told apart by line style; it sits in a strip at the top.
  const showSourceKey = opts.chartType !== "bar_chart" && groups[0].nameBySensor;
  const topOffset = TOP_OFFSET + (showSourceKey ? SOURCE_KEY_HEIGHT : 0);

  // Vertical layout: subplots, then (in legends-below mode) the slider and
  // one combined legend at the very bottom, as in the Vega-Lite charts
  const lastGridBottom =
    topOffset + groups.length * GRID_HEIGHT + (groups.length - 1) * gridGap;
  const numSeries = groups.reduce((sum, g) => sum + g.series.length, 0);
  const itemsPerRow = Math.max(Math.floor((containerWidth - GRID_LEFT - 30) / 220), 1);
  const legendHeight = Math.ceil(numSeries / itemsPerRow) * 24 + 8;
  const sliderTop = lastGridBottom + 36;
  const bottomLegendTop = sliderTop + 28 + 18;

  container.style.height = legendsBelow
    ? bottomLegendTop + legendHeight + 12 + "px"
    : topOffset + groups.length * (GRID_HEIGHT + gridGap) + BOTTOM_OFFSET + "px";

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
      textStyle: { fontSize: 15, color: "#222" },
    });
    if (!legendsBelow) {
      legends.push({
        // One vertical legend beside each subplot, listing only its own series
        data: Array.from(new Set(group.series.map((s) => s.name))),
        type: "scroll",
        tooltip: { show: true }, // hover reveals truncated names in full
        orient: "vertical",
        right: 8,
        top: top,
        height: GRID_HEIGHT,
        align: "left",
        itemWidth: 18,
        itemGap: 6,
        textStyle: { width: LEGEND_WIDTH - 40, overflow: "truncate", fontSize: 11 },
      });
    }
    xAxes.push({
      type: "time",
      gridIndex: i,
      axisLine: { onZero: false },
      axisPointer: { show: true }, // vertical ruler, as in the Vega-Lite charts
      splitLine: { show: true, lineStyle: { opacity: 0.5 } },
    });
    yAxes.push({
      type: "value",
      gridIndex: i,
      name: yAxisTitle(group.sensorType, group.units), // e.g. "Power (kW)"
      nameLocation: "end",
      nameTextStyle: {
        fontSize: 12,
        fontWeight: "bold",
        color: "#222",
        align: "left",
        padding: [0, 0, 4, -GRID_LEFT + 16],
      },
      scale: true,
      splitLine: { show: true, lineStyle: { opacity: 0.7 } },
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
        Object.assign(entry, {
          step: "start", // events hold their value for the duration of the event
          showSymbol: false,
          sampling: "lttb", // downsample to the available pixels, preserving peaks
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
      series.push(entry);
      seriesMeta.push(s);
    });
  });

  if (legendsBelow) {
    // One combined legend below all subplots, as in the Vega-Lite charts
    legends.push({
      data: Array.from(new Set(seriesMeta.map((s) => s.name))),
      type: "plain", // wraps into multiple rows
      orient: "horizontal",
      left: GRID_LEFT,
      right: 30,
      top: bottomLegendTop,
      itemWidth: 18,
      itemGap: 12,
      textStyle: { fontSize: 11 },
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
    graphic: sourceKey ? [sourceKey] : undefined,
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
      { type: "inside", xAxisIndex: allAxisIndices }, // mouse-wheel zoom and drag-to-pan
      legendsBelow
        ? { type: "slider", xAxisIndex: allAxisIndices, top: sliderTop, height: 28 }
        : { type: "slider", xAxisIndex: allAxisIndices, bottom: 14, height: 28 },
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
      nameTextStyle: { fontSize: 12, fontWeight: "bold", color: "#222" },
      axisLabel: { fontSize: 11 },
    },
    yAxis: {
      type: "value",
      name: "Count",
      nameLocation: "end",
      nameTextStyle: { fontSize: 12, fontWeight: "bold", color: "#222", align: "left", padding: [0, 0, 4, -GRID_LEFT + 16] },
      splitLine: { show: true, lineStyle: { opacity: 0.7 } },
    },
    legend: {
      data: Array.from(sources.keys()),
      type: "scroll",
      orient: opts.legendsBelow ? "horizontal" : "vertical",
      right: opts.legendsBelow ? undefined : 8,
      left: opts.legendsBelow ? GRID_LEFT : undefined,
      top: opts.legendsBelow ? TOP_OFFSET + 395 : TOP_OFFSET + 60,
      textStyle: { width: LEGEND_WIDTH - 40, overflow: "truncate", fontSize: 11 },
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
      nameTextStyle: { fontSize: 12, fontWeight: "bold", color: "#222", align: "left", padding: [0, 0, 4, -94] },
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
