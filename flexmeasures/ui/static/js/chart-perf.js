/**
 * Chart load performance reporting.
 *
 * Measures every chart load (initial page load, date range changes, data
 * refreshes, renderer switches) and produces a report with:
 * - per-request network timings and payload sizes (via the Resource Timing API)
 * - chart render time (measured by the caller around the render calls)
 * - number of data rows and total wall-clock time
 *
 * Reports are shown in a small floating panel (only on pages that load a
 * chart), logged with console.table, and downloadable as JSON.
 *
 * Usage:
 *   const report = beginChartLoad("initial page load", "standard (Vega-Lite)");
 *   ... fetch data and render, wrapping render calls with recordRender ...
 *   finishChartLoad(report, { rows: data.length });
 */

const history = [];
const MAX_HISTORY = 20;

// Endpoints that count as chart traffic
const CHART_ENDPOINT_PATTERNS = [
  "/chart_data",
  "/chart?",
  "/chart_annotations",
  "/kpis",
];

/**
 * Start measuring a chart load.
 *
 * @param {string} label - What triggered the load (e.g. "initial page load").
 * @param {string} mode - Which renderer is active (e.g. "fast (ECharts)").
 * @returns {Object} - The report object to pass to recordRender/finishChartLoad.
 */
export function beginChartLoad(label, mode) {
  return {
    label: label,
    mode: mode,
    startedAt: new Date().toISOString(),
    t0: performance.now(),
    renderMs: 0,
    rows: null,
  };
}

/**
 * Add chart render time (call with performance.now() deltas around render calls).
 */
export function recordRender(report, ms) {
  report.renderMs += ms;
}

/**
 * Finalize the report: collect network timings, log and display it.
 *
 * @param {Object} report - The report from beginChartLoad.
 * @param {Object} [extra] - Extra fields, e.g. { rows: 1234 }.
 */
export function finishChartLoad(report, extra) {
  Object.assign(report, extra || {});
  report.totalMs = round(performance.now() - report.t0);
  report.renderMs = round(report.renderMs);
  report.requests = performance
    .getEntriesByType("resource")
    .filter(
      (e) =>
        e.startTime >= report.t0 - 1 &&
        CHART_ENDPOINT_PATTERNS.some((p) => e.name.includes(p))
    )
    .map((e) => ({
      endpoint: shortEndpoint(e.name),
      durationMs: round(e.duration),
      transferKB: round((e.transferSize || 0) / 1024),
      decodedKB: round((e.decodedBodySize || 0) / 1024),
      fromCache: e.transferSize === 0 && e.decodedBodySize > 0,
    }));
  report.networkMs = round(
    report.requests.reduce((sum, r) => Math.max(sum, r.durationMs), 0)
  );
  delete report.t0;

  history.push(report);
  if (history.length > MAX_HISTORY) {
    history.shift();
  }

  console.groupCollapsed(
    "[chart-perf] " +
      report.label +
      " | " +
      report.mode +
      " | total " +
      report.totalMs +
      " ms"
  );
  console.table(report.requests);
  console.log(report);
  console.groupEnd();

  renderPanel(report);
}

function round(x) {
  return Math.round((x + Number.EPSILON) * 10) / 10;
}

function shortEndpoint(url) {
  try {
    const u = new URL(url, window.location.origin);
    return u.pathname;
  } catch (e) {
    return url;
  }
}

function renderPanel(report) {
  let panel = document.getElementById("chart-perf-panel");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "chart-perf-panel";
    panel.style.cssText =
      "position:fixed;bottom:16px;right:16px;z-index:10000;max-width:340px;" +
      "background:#fff;color:#222;border:1px solid #ccc;border-radius:8px;" +
      "box-shadow:0 2px 12px rgba(0,0,0,.25);font:12px/1.5 monospace;padding:10px 12px;";
    document.body.appendChild(panel);
  }
  const requestRows = report.requests
    .map(
      (r) =>
        "<tr><td style='padding-right:8px;'>" +
        r.endpoint +
        "</td><td style='text-align:right;'>" +
        r.durationMs +
        " ms</td><td style='text-align:right;padding-left:8px;'>" +
        (r.fromCache ? "cache" : r.transferKB + " KB") +
        "</td></tr>"
    )
    .join("");
  panel.innerHTML =
    "<div style='display:flex;justify-content:space-between;align-items:center;gap:8px;'>" +
    "<b>Chart load report #" + history.length + "</b>" +
    "<span id='chart-perf-close' style='cursor:pointer;font-size:14px;' title='Hide report'>&times;</span>" +
    "</div>" +
    "<div>" + report.label + " &mdash; " + report.mode + "</div>" +
    "<table style='margin-top:4px;'>" +
    "<tr><td>data rows</td><td style='text-align:right;'><b>" + (report.rows === null ? "n/a" : report.rows) + "</b></td></tr>" +
    "<tr><td>network (longest request)</td><td style='text-align:right;'><b>" + report.networkMs + " ms</b></td></tr>" +
    "<tr><td>chart render</td><td style='text-align:right;'><b>" + report.renderMs + " ms</b></td></tr>" +
    "<tr><td>total</td><td style='text-align:right;'><b>" + report.totalMs + " ms</b></td></tr>" +
    "</table>" +
    "<details style='margin-top:4px;'><summary style='cursor:pointer;'>" +
    report.requests.length + " request(s)</summary>" +
    "<table>" + requestRows + "</table></details>" +
    "<a href='#' id='chart-perf-download' style='display:inline-block;margin-top:4px;'>Download history (JSON)</a>";

  panel.querySelector("#chart-perf-close").addEventListener("click", () => {
    panel.remove(); // reappears on the next chart load
  });
  panel.querySelector("#chart-perf-download").addEventListener("click", (e) => {
    e.preventDefault();
    const blob = new Blob([JSON.stringify(history, null, 2)], {
      type: "application/json",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "chart-load-reports.json";
    a.click();
    URL.revokeObjectURL(a.href);
  });
}
