/** Remember the selected graph window independently of chart rendering and data caching. */
const STORAGE_KEY = "fm-chart-date-range";

function validRange(start, end) {
  if (!start || !end) return null;
  const from = new Date(typeof start === "string" ? start.replace(" ", "+") : start);
  const until = new Date(typeof end === "string" ? end.replace(" ", "+") : end);
  return Number.isFinite(from.getTime()) && Number.isFinite(until.getTime()) && from < until
    ? { start: from, end: until }
    : null;
}

/** Explicit links win over the last selection, with the old server session as fallback. */
export function restoreChartDateRange(search, sessionStart, sessionEnd) {
  const params = new URLSearchParams(search);
  const linked = validRange(params.get("start_time"), params.get("end_time"));
  if (linked) return linked;
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    const range = saved && validRange(saved.start, saved.end);
    if (range) return range;
  } catch (_) {
    // Storage may be unavailable or contain an invalid value. The graph still works.
  }
  return validRange(sessionStart, sessionEnd);
}

/** Store the full selected window, including when all its data is already cached. */
export function rememberChartDateRange(start, end) {
  const range = validRange(start, end);
  if (!range) return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(range));
  } catch (_) {
    // Browsers that disallow storage can still display the selected range.
  }
}
