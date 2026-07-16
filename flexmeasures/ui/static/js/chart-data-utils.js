/**
 * Utilities for processing and validating sensor data for visualization.
 * 
 * - Adapts compressed API responses (>= FM v0.28) into the legacy format required by the charts.
 * - Validates time ranges for Daylight Saving Time (DST) transitions.
 * - Checks for potential data masking issues (e.g., multiple sources in heatmaps).
 * - Triggers UI notifications (Toasts) to warn users about data anomalies.
 * 
 * Dependencies:
 * - Requires the global `showToast` function to be available for user alerts.
 */

import { getUniqueValues } from "./data-utils.js";
import { countDSTTransitions } from "./daterange-utils.js";

/**
 * Convert data from the new (>= FM v0.28) compressed reference-based format
 * back to the old format, for backward compatibility.
 *
 * @param {Object} responseData - The data from the sensor data API.
 * @returns {Object[]} - The adapted data in the old format.
 */
export function decompressChartData(responseData) {
  // Check if it's the new compressed reference-based format, if so: decompress
  if (responseData.data && responseData.sensors && responseData.sources) {
    return responseData.data.map((belief) => {
      const sensor = responseData.sensors[belief.sid] || {};
      const source = responseData.sources[belief.src] || {};

      // Special case: for sensors with seconds unit, convert to datetime here
      const value =
        sensor.unit === "s" && typeof belief.val === "number"
          ? new Date(belief.val * 1000)
          : belief.val;
      return {
        // Map shortened field names back to original names
        event_start: belief.ts,
        event_value: value,
        belief_horizon: belief.bh,
        scale_factor: belief.sf,
        belief_time: belief.bt,

        // Reconstruct full sensor and source objects
        sensor: {
          id: belief.sid,
          name: sensor.name || "",
          sensor_unit: sensor.unit || "",
          unit: sensor.unit || "",
          event_resolution: sensor.event_resolution,
          description: sensor.description || "",
          asset_id: sensor.asset_id,
          asset_description: sensor.asset_description || "",
        },
        source: {
          ...source,
          id: belief.src,
          name: source.name || "",
          model: source.model || "",
          version: source.version || "",
          type: source.type || "other",
          raw_type: source.raw_type || "",
          display_type:
            source.display_type || source.raw_type || source.type || "other",
          description: source.description || "",
        },

        // Keep sensor_unit at root level for backward compatibility
        sensor_unit: sensor.unit || "",
      };
    });
  }

  // If it's already in the old format, return as-is
  return responseData;
}

export function checkDSTTransitions(startDate, endDate) {
  var numDSTTransitions = countDSTTransitions(startDate, endDate, 90);
  if (numDSTTransitions == 1) {
    showToast(
      "Please note that the sensor data you are viewing includes a daylight saving time (DST) transition."
    );
  } else if (numDSTTransitions > 1) {
    showToast(
      "Please note that the sensor data you are viewing includes " +
        numDSTTransitions +
        " daylight saving time (DST) transitions."
    );
  }
}

export function checkSourceMasking(data, chartType) {
  var uniqueSourceIds = getUniqueValues(data, "source.id");
  if (chartType == "daily_heatmap" && uniqueSourceIds.length > 1) {
    showToast(
      "Please note that only data from the most prevalent source is shown."
    );
  }
}

/**
 * Warn when loaded belief data falls outside a sub-chart's "Strict range…"
 * y-axis, since that data is drawn clamped to the nearest edge rather than
 * shown at its true value.
 *
 * @param {Object[]} data - Belief data, each with a `sensor.id` and `event_value`.
 * @param {Object[]} sensorsToShow - The asset's `sensors_to_show` entries.
 */
// Remembers the last set of strict-range warnings shown, so calling
// checkStrictYAxisRanges repeatedly (e.g. from both the data-load path and the
// fast-chart render path) doesn't re-toast the same warning. Reset to "" whenever
// nothing is out of range, so a later out-of-range state warns again.
let lastStrictWarningKey = "";

export function checkStrictYAxisRanges(data, sensorsToShow) {
  if (!Array.isArray(sensorsToShow)) return;
  const warnings = [];
  for (const entry of sensorsToShow) {
    const yAxis = entry["y-axis"];
    const isStrict =
      yAxis !== null &&
      typeof yAxis === "object" &&
      !Array.isArray(yAxis) &&
      typeof yAxis.min === "number" &&
      typeof yAxis.max === "number";
    if (!isStrict) continue;

    const sensorIds = new Set();
    for (const plot of entry.plots || []) {
      if (typeof plot.sensor === "number") sensorIds.add(plot.sensor);
      if (Array.isArray(plot.sensors)) {
        for (const id of plot.sensors) sensorIds.add(id);
      }
    }
    if (sensorIds.size === 0) continue;

    const outOfRange = data.some(
      (datum) =>
        sensorIds.has(datum.sensor && datum.sensor.id) &&
        typeof datum.event_value === "number" &&
        (datum.event_value < yAxis.min || datum.event_value > yAxis.max),
    );
    if (outOfRange) {
      warnings.push(
        `'${entry.title || "A graph"}' has data outside its strict y-axis range (${yAxis.min} to ${yAxis.max}); those values are shown clamped to the nearest edge.`,
      );
    }
  }

  // De-duplicate: only toast when the set of warnings changed since last time.
  const key = warnings.join("\n");
  if (key === lastStrictWarningKey) return;
  lastStrictWarningKey = key;
  for (const message of warnings) {
    showToast(message, "warning");
  }
}
