/**
 * Single place where the asset/sensor pages fetch time series data for their charts.
 *
 * Before this module, four call sites in graphs.html each built the same `/chart_data` query string,
 * and repeated the same response handling.
 * Keeping that in one place means the request shape is defined once,
 * and it gives the interval cache (see chart-data-cache.js) a single point to hook into.
 *
 * Dependencies:
 * - `decompressChartData` from chart-data-utils.js, to adapt the compressed (>= FM v0.28) response.
 */

import { decompressChartData } from "./chart-data-utils.js";

/**
 * Build the URL for a chart data request.
 *
 * @param {string} dataPath - Base path of the asset or sensor, e.g. '/api/v3_0/assets/1'.
 * @param {Object} options
 * @param {Date} options.start - Start of the event window (inclusive).
 * @param {Date} options.end - End of the event window (exclusive).
 * @param {boolean} [options.mostRecentBeliefsOnly] - Pass false to get every recorded belief, as the replay does.
 * @returns {string} - The URL to fetch.
 */
export function buildChartDataUrl(dataPath, { start, end, mostRecentBeliefsOnly }) {
  let url =
    dataPath +
    "/chart_data?event_starts_after=" +
    start.toISOString() +
    "&event_ends_before=" +
    end.toISOString();
  if (mostRecentBeliefsOnly === false) {
    url += "&most_recent_beliefs_only=false";
  }
  return url + "&compress_json=true";
}

/**
 * Fetch chart data for one event window, already decompressed into belief records.
 *
 * @param {string} dataPath - Base path of the asset or sensor.
 * @param {Object} options - As for buildChartDataUrl, plus an optional AbortSignal.
 * @param {AbortSignal} [options.signal] - Signal used to abort in-flight requests.
 * @returns {Promise<Object[]>} - Belief records in the format the charts expect.
 */
export function fetchChartData(dataPath, options) {
  return fetch(buildChartDataUrl(dataPath, options), {
    method: "GET",
    headers: { "Content-Type": "application/json" },
    signal: options.signal,
  })
    .then((response) => response.json())
    .then((data) => decompressChartData(data));
}

/**
 * Fetch the annotations to show alongside the chart data for one event window.
 *
 * @param {string} dataPath - Base path of the asset or sensor.
 * @param {Object} options
 * @param {Date} options.start - Start of the event window (inclusive).
 * @param {Date} options.end - End of the event window (exclusive).
 * @param {AbortSignal} [options.signal] - Signal used to abort in-flight requests.
 * @returns {Promise<Object[]>} - Annotation records.
 */
export function fetchChartAnnotations(dataPath, { start, end, signal }) {
  const url =
    dataPath +
    "/chart_annotations?event_starts_after=" +
    start.toISOString() +
    "&event_ends_before=" +
    end.toISOString();
  return fetch(url, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
    signal: signal,
  }).then((response) => response.json());
}
