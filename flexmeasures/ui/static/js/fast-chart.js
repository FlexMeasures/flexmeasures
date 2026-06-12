/**
 * Fast (canvas-based) time series rendering with Apache ECharts.
 *
 * This module offers an alternative to the Vega-Lite charts for users who want
 * snappier rendering and interaction on dense time series:
 * - canvas rendering (no per-mark DOM nodes)
 * - built-in LTTB downsampling per series (`sampling: "lttb"`)
 * - mouse-wheel zoom, drag-to-pan and a range slider, synced across subplots
 *
 * It consumes the same rows as the Vega-Lite charts (the decompressed output
 * of the /chart_data endpoints): objects with `event_start` (ms epoch),
 * `event_value`, `belief_horizon` (ms), and nested `sensor` and `source`
 * objects. Layout and tooltips mirror the Vega-Lite charts: centered subplot
 * titles, "Sensor-type (unit)" y-axis titles, and per-point tooltips listing
 * sensor, value, time, horizon and source details.
 *
 * Dependencies: the global `echarts` object (loaded in base.html).
 */

const GRID_HEIGHT = 220; // height of each subplot in px
const GRID_GAP = 56; // vertical space between subplots (axis labels + titles)
const TOP_OFFSET = 48; // room for the toolbox and the first subplot title
const BOTTOM_OFFSET = 78; // room for the slider and the last x-axis labels
const GRID_LEFT = 70; // room for the y-axis labels
const LEGEND_WIDTH = 190; // width of the legend column beside each subplot

// One chart instance per container element
const instances = {};

/**
 * Group chart data rows into subplots and series (one series per
 * sensor+source combination).
 *
 * When a group spec is given (the asset's sensors_to_show structure), the
 * subplots mirror the Vega-Lite chart: one subplot per spec entry, in order,
 * each with its title and sensors. Spec entries without data still get an
 * (empty) subplot, so no chart goes missing. Rows from sensors not covered
 * by the spec — and all rows when there is no spec, as on the sensor page —
 * are grouped by unit.
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

  for (const row of data) {
    if (typeof row.event_value !== "number" || row.event_value === null) {
      continue; // fast charts only render numeric series
    }
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

  return groups.map((group) => {
    const series = [];
    for (const s of group.series.values()) {
      s.points.sort((a, b) => a[0] - b[0]);
      // Series names must be globally unique, so that each subplot's legend
      // only toggles its own series (names are shared state across legends).
      s.name = s.sensorName + " · " + s.sourceLabel;
      s.sensorType = group.sensorType || s.sensorName;
      series.push(s);
    }
    const sensorNames = Array.from(group.sensorNames);
    return {
      title: group.title || sensorNames.join(", "),
      units: Array.from(group.units),
      sensorType: group.sensorType,
      multiSensor: group.sensorNames.size > 1,
      series: series,
    };
  });
}

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
function formatFullDate(ms) {
  const d = new Date(ms);
  const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const pad = (n) => String(n).padStart(2, "0");
  return (
    pad(d.getHours()) + ":" + pad(d.getMinutes()) +
    " on " + days[d.getDay()] + " " + months[d.getMonth()] +
    " " + d.getDate() + ", " + d.getFullYear()
  );
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

// Tooltip matching the Vega-Lite charts: a two-column table per data point
function tooltipFormatter(seriesMeta) {
  return function (params) {
    if (params.componentType === "legend") {
      return escapeHtml(params.name); // legend hover: just reveal the full series name
    }
    const meta = seriesMeta[params.seriesIndex];
    if (!meta) {
      return "";
    }
    const value = params.value;
    const rows = [
      ["Sensor", meta.sensorDescription],
      [capFirst(meta.sensorType), formatQuantity(value[1], meta.unit)],
      ["Time and date", formatFullDate(value[0])],
      ["Horizon", formatTimedelta(value[2])],
      ["Source", meta.source.name + " (ID: " + meta.source.id + ")"],
      ["Type", meta.source.display_type || ""],
      ["Model", meta.source.model || ""],
      ["Version", meta.source.version || ""],
    ];
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
  };
}

/**
 * Render (or re-render) the fast chart into the given container element.
 *
 * @param {string} elementId - The id of the container div.
 * @param {Object[]} data - Decompressed chart data rows.
 * @param {Object} [options] - Optional settings: { groupSpec } (see groupData).
 */
export function renderFastChart(elementId, data, options) {
  const container = document.getElementById(elementId);
  if (!container || typeof echarts === "undefined") {
    return;
  }
  const groups = groupData(data || [], options && options.groupSpec);

  // Size the container to fit all subplots before initializing the chart
  const numGrids = Math.max(groups.length, 1);
  container.style.height =
    TOP_OFFSET + numGrids * (GRID_HEIGHT + GRID_GAP) + BOTTOM_OFFSET + "px";

  let instance = instances[elementId];
  if (!instance || instance.chart.isDisposed()) {
    const chart = echarts.init(container, null, { renderer: "canvas" });
    instance = { chart: chart, resizeTimer: null, lastArgs: null };
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
  } else {
    instance.chart.resize(); // container height may have changed with the number of subplots
  }
  instance.lastArgs = { data: data, options: options };
  const chart = instance.chart;

  if (groups.length === 0) {
    chart.clear();
    chart.setOption({
      title: {
        text: "No data to show for this time range",
        left: "center",
        top: "middle",
        textStyle: { fontWeight: "normal", color: "#888" },
      },
    });
    return;
  }

  // Center each subplot title over its plot area (not over the legend column)
  const containerWidth = container.clientWidth || 800;
  const plotCenter = (GRID_LEFT + containerWidth - LEGEND_WIDTH - 40) / 2;

  const grids = [];
  const xAxes = [];
  const yAxes = [];
  const titles = [];
  const legends = [];
  const series = [];
  const seriesMeta = [];

  groups.forEach((group, i) => {
    const top = TOP_OFFSET + i * (GRID_HEIGHT + GRID_GAP);
    grids.push({
      top: top,
      height: GRID_HEIGHT,
      left: GRID_LEFT,
      right: LEGEND_WIDTH + 40, // leave room for the legend beside the subplot
      containLabel: false,
    });
    titles.push({
      text: group.title,
      left: plotCenter,
      textAlign: "center",
      top: top - 42,
      textStyle: { fontSize: 15, color: "#222" },
    });
    legends.push({
      // One vertical legend beside each subplot, listing only its own series
      data: group.series.map((s) => s.name),
      orient: "vertical",
      type: "scroll",
      right: 8,
      top: top,
      height: GRID_HEIGHT,
      align: "left",
      itemWidth: 18,
      itemGap: 6,
      // For single-sensor subplots the sensor is already in the title, so only show the source
      formatter: group.multiSensor
        ? undefined
        : (name) => name.split(" · ").slice(1).join(" · ") || name,
      textStyle: {
        width: LEGEND_WIDTH - 40,
        overflow: "truncate",
        fontSize: 11,
      },
      tooltip: { show: true }, // hover reveals truncated names in full
    });
    xAxes.push({
      type: "time",
      gridIndex: i,
      axisLine: { onZero: false },
      axisPointer: { show: true }, // vertical ruler, as in the Vega-Lite charts
      splitLine: { show: true, lineStyle: { opacity: 0.5 } },
    });
    // Y-axis title as in the Vega-Lite charts, e.g. "Power (kW)"
    const unitLabel = group.units.join(", ");
    const yTitle = group.sensorType
      ? capFirst(group.sensorType) + (unitLabel ? " (" + unitLabel + ")" : "")
      : unitLabel;
    yAxes.push({
      type: "value",
      gridIndex: i,
      name: yTitle,
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
    for (const s of group.series) {
      series.push({
        name: s.name,
        type: "line",
        xAxisIndex: i,
        yAxisIndex: i,
        data: s.points,
        step: "start", // events hold their value for the duration of the event
        showSymbol: false,
        sampling: "lttb", // downsample to the available pixels, preserving peaks
        lineStyle: { width: 2.2 },
        emphasis: { focus: "series" },
        animation: false,
      });
      seriesMeta.push(s);
    }
  });

  const allAxisIndices = xAxes.map((_, i) => i);

  chart.clear();
  chart.setOption({
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
      formatter: tooltipFormatter(seriesMeta),
    },
    toolbox: {
      right: 16,
      feature: {
        dataZoom: { xAxisIndex: allAxisIndices, yAxisIndex: false },
        restore: {},
        saveAsImage: { name: "flexmeasures-chart" },
      },
    },
    dataZoom: [
      {
        type: "inside", // mouse-wheel zoom and drag-to-pan
        xAxisIndex: allAxisIndices,
      },
      {
        type: "slider",
        xAxisIndex: allAxisIndices,
        bottom: 14,
        height: 28,
      },
    ],
  });
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
