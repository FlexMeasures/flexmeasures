/**
 * Reuse of already-fetched chart data when the selected time window changes.
 *
 * Selecting a new window usually keeps most of the old one:
 * stepping a week forward by a day, extending a year by a day, or zooming back out to a span just left behind.
 * Rather than re-querying the whole window, we keep the records we already have,
 * and fetch only the parts that are new (FlexMeasures issue #101).
 *
 * The date picker only ever yields whole (nominal) days,
 * so a selection is always one contiguous range and the slivers are always whole days.
 * That is why a single loaded interval suffices here,
 * and why interval arithmetic is done on Date objects rather than on millisecond counts:
 * a nominal day is 23 or 25 hours across a daylight saving time transition.
 */

import { fetchChartData } from "./chart-data-fetch.js";

/**
 * Work out which parts of a newly selected window are not covered by the loaded one.
 *
 * Both windows are half-open, [start, end), for sensors that have a resolution.
 * Instantaneous sensors are the exception: the API matches those on both edges inclusively,
 * so an instant falling exactly on a boundary belongs to the windows on either side of it.
 * That costs nothing here, because such an instant is fetched by both and then de-duplicated.
 *
 * @param {Date} start - Start of the newly selected window.
 * @param {Date} end - End of the newly selected window.
 * @param {?Object} loaded - The window whose data is in memory, as {start: Date, end: Date}.
 * @returns {Object[]} - Zero, one or two {start, end} ranges still to fetch.
 */
export function missingRanges(start, end, loaded) {
  // Nothing loaded, or the two windows do not touch: everything is new.
  if (!loaded || !loaded.start || !loaded.end) return [{ start: start, end: end }];
  if (end <= loaded.start || start >= loaded.end) return [{ start: start, end: end }];

  const ranges = [];
  if (start < loaded.start) ranges.push({ start: start, end: loaded.start });
  if (end > loaded.end) ranges.push({ start: loaded.end, end: end });
  return ranges;
}

/**
 * The resolution, in milliseconds, that the loaded events are actually spaced on.
 *
 * The API resamples every sensor with a non-zero resolution to the finest resolution among the sensors requested,
 * but still reports each sensor's own resolution,
 * so the spacing has to be derived rather than read off a record.
 * Instantaneous sensors (resolution zero) are never resampled and are excluded here.
 *
 * @param {Object[]} records - Belief records carrying `sensor.event_resolution` in seconds.
 * @returns {number} - The resolution in milliseconds, or 0 if every sensor is instantaneous.
 */
export function effectiveResolutionMs(records) {
  let finest = 0;
  for (const record of records || []) {
    const seconds = record.sensor ? record.sensor.event_resolution : 0;
    if (seconds > 0 && (finest === 0 || seconds < finest)) finest = seconds;
  }
  return finest * 1000;
}

/**
 * Is a window on the same resampling grid as the span already loaded?
 *
 * The API anchors its resampling at the start of the window asked for,
 * so a window offset from the loaded span by a fraction of the resolution comes back on shifted timestamps,
 * which cannot be reconciled with what is held.
 * Whole-day selections of sensors whose resolution divides a day are always aligned;
 * this guards the rest, such as a 7-minute sensor shown alongside an hourly one.
 *
 * @param {Date} loadedStart - Start of the loaded span.
 * @param {Date} start - Start of the window being selected.
 * @param {Date} end - End of the window being selected.
 * @param {number} resolutionMs - Resolution the loaded events are spaced on.
 * @returns {boolean} - Whether the loaded records can be reused for this window.
 */
export function onSameResamplingGrid(loadedStart, start, end, resolutionMs) {
  if (!resolutionMs) return true;
  const base = loadedStart.getTime();
  return (
    (start.getTime() - base) % resolutionMs === 0 &&
    (end.getTime() - base) % resolutionMs === 0
  );
}

/**
 * Keep the records that a direct fetch of this window would have returned.
 *
 * The API selects events that *overlap* the window rather than events that start inside it,
 * so an event running across the window's start belongs in the result.
 * Filtering on `event_start` alone would drop it,
 * and the chart would then be missing its leading event whenever the resolution does not line up with the window's edge.
 * Instantaneous events are matched inclusively on both edges, as the API does.
 *
 * @param {Object[]} records - Belief records, each with an `event_start` in milliseconds.
 * @param {Date} start - Start of the window.
 * @param {Date} end - End of the window.
 * @param {number} resolutionMs - Resolution the records are spaced on.
 * @returns {Object[]} - The records belonging to the window.
 */
export function clipToWindow(records, start, end, resolutionMs) {
  const from = start.getTime();
  const until = end.getTime();
  return (records || []).filter((record) => {
    const isInstantaneous = !record.sensor || !record.sensor.event_resolution;
    if (isInstantaneous) {
      return record.event_start >= from && record.event_start <= until;
    }
    return record.event_start < until && record.event_start + resolutionMs > from;
  });
}

/**
 * Drop records that describe the same belief twice.
 *
 * Splitting a window can hand back one event on both sides of the seam,
 * when the sensor's resolution does not divide the window evenly (verified in test_chart_data_window_splitting.py).
 * Records are never lost that way, only repeated, so de-duplicating is enough.
 *
 * @param {Object[]} records - Belief records to de-duplicate, keeping the first of each.
 * @returns {Object[]} - The records without repeats.
 */
export function dedupeRecords(records) {
  const seen = new Set();
  return records.filter((record) => {
    const sensorId = record.sensor ? record.sensor.id : undefined;
    const sourceId = record.source ? record.source.id : undefined;
    const key = `${sensorId}|${record.event_start}|${sourceId}|${record.belief_time}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/**
 * Create a cache that serves chart data for a window, fetching only what it lacks.
 *
 * The cache holds the widest contiguous span loaded so far, not just the span on display,
 * so narrowing the selection and widening it again costs nothing.
 * Its size is therefore bounded by the widest contiguous span the user has browsed,
 * which is what selecting that span in one go would have loaded anyway.
 *
 * Selecting a window that does not touch the cached span replaces it,
 * keeping the cached span contiguous.
 *
 * The merged records are deliberately not re-sorted:
 * the fast chart sorts each series by time itself,
 * and Vega-Lite sorts line and area marks by their x channel.
 *
 * @returns {Object} - A cache with `load(dataPath, options)` and `reset()`.
 */
export function createChartDataCache() {
  let cached = null;

  return {
    /**
     * Forget everything held, e.g. because the underlying data changed.
     */
    reset() {
      cached = null;
    },

    /**
     * Return the records for a window, fetching only the parts not already held.
     *
     * @param {string} dataPath - Base path of the asset or sensor.
     * @param {Object} options
     * @param {Date} options.start - Start of the newly selected window.
     * @param {Date} options.end - End of the newly selected window.
     * @param {boolean} [options.mostRecentBeliefsOnly] - Pass false to get every recorded belief.
     * @param {AbortSignal} [options.signal] - Signal used to abort in-flight requests.
     * @returns {Promise<Object[]>} - Belief records covering exactly the newly selected window.
     */
    async load(dataPath, options) {
      const { start, end, mostRecentBeliefsOnly, signal } = options;
      // Work from a snapshot throughout.
      // Selections are not serialised and their requests are not aborted,
      // so a second selection can replace what is held while this one is still awaiting its data.
      // Merging against the snapshot keeps each result's span and records describing the same thing.
      const held = cached;
      const resolutionMs = held ? effectiveResolutionMs(held.data) : 0;
      // Reuse only what a direct fetch would have returned identically.
      // Windows that merely touch still form one contiguous span,
      // so they extend the cache rather than replace it:
      // stepping a selection on by exactly its own width keeps both.
      const reusable =
        held !== null &&
        end >= held.start &&
        start <= held.end &&
        onSameResamplingGrid(held.start, start, end, resolutionMs);
      const ranges = missingRanges(start, end, reusable ? held : null);

      let assembled = held;
      if (ranges.length > 0) {
        const fetched = await Promise.all(
          ranges.map((range) =>
            fetchChartData(dataPath, {
              start: range.start,
              end: range.end,
              mostRecentBeliefsOnly: mostRecentBeliefsOnly,
              signal: signal,
            })
          )
        );
        assembled = reusable
          ? {
              start: start < held.start ? start : held.start,
              end: end > held.end ? end : held.end,
              data: dedupeRecords(held.data.concat(...fetched)),
            }
          : { start: start, end: end, data: [].concat(...fetched) };
        // Whichever selection finishes last decides what is held.
        // Both spans are self-consistent, so the worst case is a later selection re-fetching.
        cached = assembled;
      }

      return clipToWindow(assembled.data, start, end, effectiveResolutionMs(assembled.data));
    },
  };
}
