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
          description: sensor.description || "",
          asset_id: sensor.asset_id,
          asset_description: sensor.asset_description || "",
        },
        source: {
          id: belief.src,
          name: source.name || "",
          model: source.model || "",
          type: source.type || "other",
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
