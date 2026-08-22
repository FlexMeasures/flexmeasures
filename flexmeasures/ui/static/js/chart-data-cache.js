/**
 * Reuse of already-fetched chart data when the selected time window changes.
 *
 * Selecting a new window usually keeps most of the old one: stepping a week forward by
 * a day, or extending a year by a day, changes only a sliver.
 * Rather than re-querying the whole window, we keep the records we already have and
 * fetch only the parts that are new (FlexMeasures issue #101).
 *
 * The date picker only ever yields whole (nominal) days, so a selection is always one
 * contiguous range and the slivers are always whole days.
 * That is why a single loaded interval suffices here, and why interval arithmetic is
 * done on Date objects rather than on millisecond counts: a nominal day is 23 or 25
 * hours across a daylight saving time transition.
 */

import { fetchChartData } from "./chart-data-source.js";

/**
 * Work out which parts of a newly selected window are not covered by the loaded one.
 *
 * Both windows are half-open, [start, end), matching how the API treats
 * `event_starts_after` and `event_ends_before`.
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
 * Keep only the records for events that start inside the given window.
 *
 * This matches the API's own filtering, which returns events starting at or after
 * `event_starts_after`, so trimming here yields what a fetch would have returned.
 *
 * @param {Object[]} records - Belief records, each with an `event_start` in milliseconds.
 * @param {Date} start - Start of the window (inclusive).
 * @param {Date} end - End of the window (exclusive).
 * @returns {Object[]} - The records falling inside the window.
 */
export function clipToWindow(records, start, end) {
  const from = start.getTime();
  const until = end.getTime();
  return (records || []).filter(
    (record) => record.event_start >= from && record.event_start < until
  );
}

/**
 * Drop records that describe the same belief twice.
 *
 * Splitting a window can hand back one event on both sides of the seam, when the
 * sensor's resolution does not divide the window evenly (verified in
 * test_chart_data_window_splitting.py).
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
 * Fetch the data for a window, reusing whatever the previous window already provides.
 *
 * Falls back to fetching the whole window whenever there is nothing to reuse, so the
 * caller does not need to distinguish the cases.
 *
 * The merged records are deliberately not re-sorted: the fast chart sorts each series
 * by time itself, and Vega-Lite sorts line and area marks by their x channel.
 *
 * @param {string} dataPath - Base path of the asset or sensor.
 * @param {Object} options
 * @param {Date} options.start - Start of the newly selected window.
 * @param {Date} options.end - End of the newly selected window.
 * @param {boolean} [options.mostRecentBeliefsOnly] - Pass false to get every recorded belief.
 * @param {AbortSignal} [options.signal] - Signal used to abort in-flight requests.
 * @param {?Object} previous - Previously loaded {start, end, data}, or null.
 * @returns {Promise<Object[]>} - Belief records covering the whole newly selected window.
 */
export async function fetchWindowReusingPrevious(dataPath, options, previous) {
  const { start, end, mostRecentBeliefsOnly, signal } = options;
  const ranges = missingRanges(start, end, previous);
  const reused = previous ? clipToWindow(previous.data, start, end) : [];

  // The new window is fully covered by what we already have (e.g. zooming back in).
  if (ranges.length === 0) return dedupeRecords(reused);

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
  if (reused.length === 0) return [].concat(...fetched);
  return dedupeRecords(reused.concat(...fetched));
}
