/**
 * Preview and confirm draft sensor values before saving them (#2469), the second step of the "Draft values" panel.
 *
 * The user chooses whether to repeat the draft values (daily, on workdays, on weekends, or on the same weekday only) and until when.
 * POST /sensors/<id>/data repeats them on the server, from the draft values with `repeat` and `until`,
 * which resolves daylight saving time transitions and reports what they did.
 * The preview is a dry run of that request, which runs as soon as the step opens, and again on each change of these choices.
 * It shows what will be saved on the chart, with the existing values it updates,
 * and Confirm sends the same request without the dry run, so the server saves exactly what it previewed.
 *
 * The pure functions build the requests and read their answers; wirePreviewStep connects them to the panel.
 * Values are kept as slots: { start: Date, end: Date, value: number }, like draft values.
 */

import { DRAFT_VALUES_RECORDED_EVENT, formatIsoDuration } from "./draft-values.js";
import { extractApiErrorMessage } from "./ui-utils.js";

// The repeat choices, as POST /sensors/<id>/data names them ("none" means saving the draft values only).
export const REPEAT_CHOICES = ["none", "daily", "workdays", "weekends", "same-weekday"];

// Raised when draft values cannot be previewed or saved as asked; its message is meant for the user.
export class PreviewError extends Error {
  constructor(message) {
    super(message);
    this.name = "PreviewError";
  }
}

/**
 * The local date of a time in a timezone.
 *
 * @param {Date} date - The time.
 * @param {string} timeZone - An IANA timezone, such as "Europe/Amsterdam".
 * @returns {string} The date, e.g. "2026-10-25".
 */
export function localDate(date, timeZone) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: timeZone, year: "numeric", month: "2-digit", day: "2-digit" })
    .formatToParts(date);
  const part = (type) => parts.find((p) => p.type === type).value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function parseDate(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  return { year, month, day };
}

function formatDate({ year, month, day }) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${String(year).padStart(4, "0")}-${pad(month)}-${pad(day)}`;
}

function addDays(isoDate, days) {
  const { year, month, day } = parseDate(isoDate);
  const shifted = new Date(Date.UTC(year, month - 1, day + days));
  return formatDate({ year: shifted.getUTCFullYear(), month: shifted.getUTCMonth() + 1, day: shifted.getUTCDate() });
}

// One year later, on the last day of the month when that day does not exist (29 February), as pandas' DateOffset does.
function addYear(isoDate) {
  const { year, month, day } = parseDate(isoDate);
  const lastDay = new Date(Date.UTC(year + 1, month, 0)).getUTCDate();
  return formatDate({ year: year + 1, month: month, day: Math.min(day, lastDay) });
}

/**
 * The dates the draft values may be repeated until, in the sensor's timezone.
 *
 * The earliest is the first date a repeat lands on (the day after the draft values start, or a week after for the same weekday),
 * and the latest is one year after they start, the cap of POST /sensors/<id>/data.
 * The default is one week after they start.
 *
 * @param {Object[]} drafts - The draft values, sorted by start.
 * @param {string} timeZone - The sensor's timezone.
 * @param {string} repeat - "daily" or "same-weekday".
 * @returns {{min: string, max: string, default: string}} Dates, e.g. "2026-11-01".
 */
export function untilBounds(drafts, timeZone, repeat) {
  const first = localDate(drafts[0].start, timeZone);
  const min = addDays(first, repeat === "same-weekday" ? 7 : 1);
  const max = addYear(first);
  const preferred = addDays(first, 7);
  return { min: min, max: max, default: preferred < min ? min : preferred > max ? max : preferred };
}

// An ISO 8601 time without milliseconds, which the API reads, e.g. "2026-10-25T00:00:00Z".
function isoInstant(ms) {
  return new Date(ms).toISOString().replace(/\.000Z$/, "Z");
}

/**
 * The draft values as one pattern, in the shape of POST /sensors/data, with null for the slots between them.
 *
 * Values are laid out in fixed steps of the resolution, as the API reads them.
 * That fails only for daily slots across a daylight saving time transition, whose day is 23 or 25 hours long.
 *
 * @param {Object[]} drafts - The draft values, sorted by start.
 * @param {number} resolutionMs - The sensor's event resolution, in milliseconds.
 * @param {string} unit - The unit of the values.
 * @returns {{start: string, duration: string, values: (number|null)[], unit: string}} The pattern.
 * @throws {PreviewError} When there are no draft values, or they do not fall on one grid of fixed steps.
 */
export function draftsToPattern(drafts, resolutionMs, unit) {
  if (drafts.length === 0) throw new PreviewError("There are no draft values to save.");
  const t0 = drafts[0].start.getTime();
  const steps = drafts.map((draft) => (draft.start.getTime() - t0) / resolutionMs);
  if (!steps.every(Number.isInteger)) {
    throw new PreviewError(
      "These draft values do not fall on one regular series of slots, as a daylight saving time transition makes one of their days longer or shorter. " +
      "Save the draft values before and after the transition separately.",
    );
  }
  const values = new Array(steps[steps.length - 1] + 1).fill(null);
  drafts.forEach((draft, k) => {
    values[steps[k]] = draft.value;
  });
  return { start: isoInstant(t0), duration: formatIsoDuration(values.length * resolutionMs), values: values, unit: unit };
}

/**
 * The body for POST /sensors/<id>/data that repeats the draft values: the pattern, with `repeat` and `until`.
 *
 * Send it with `dry-run` to preview what it would save, and without, to save that.
 *
 * @param {Object} pattern - A pattern from draftsToPattern.
 * @param {string} repeat - One of REPEAT_CHOICES other than "none".
 * @param {string} until - The last date to repeat on, e.g. "2026-11-01".
 * @returns {Object} The body.
 */
export function repeatRequestBody(pattern, repeat, until) {
  return { ...pattern, values: pattern.values.slice(), repeat: repeat, until: until };
}

/**
 * The slots with a value in a regular series of values, such as a GET /sensors/data response.
 *
 * @param {{start: string, values: (number|null)[]}} series - The series, starting at an ISO 8601 time.
 * @param {number} resolutionMs - The resolution of the series, in milliseconds.
 * @returns {Object[]} The slots, sorted by start, leaving out null values.
 */
export function gridToPoints(series, resolutionMs) {
  const t0 = Date.parse(series.start);
  const points = [];
  series.values.forEach((value, i) => {
    if (value === null || value === undefined) return;
    const start = t0 + i * resolutionMs;
    points.push({ start: new Date(start), end: new Date(start + resolutionMs), value: value });
  });
  return points;
}

/**
 * The slots with a value in the regular series of a dry run's `data`.
 *
 * Usually there is one series, but a new one starts wherever the values are not one resolution apart,
 * such as where the clock change of a far-away timezone is shorter than the resolution.
 *
 * @param {Object[]} chunks - The dry run's `data`.
 * @param {number} resolutionMs - The sensor's event resolution, in milliseconds.
 * @returns {Object[]} The slots, sorted by start.
 */
export function chunksToPoints(chunks, resolutionMs) {
  return chunks
    .flatMap((chunk) => gridToPoints(chunk, resolutionMs))
    .sort((a, b) => a.start - b.start);
}

/**
 * The query for GET /sensors/data that loads the existing values over the range of the values to save.
 *
 * @param {Object[]} points - The slots to save, sorted by start.
 * @param {string} unit - The unit to load the existing values in.
 * @param {number|null} [sourceId] - Only load the values of this data source.
 * @returns {URLSearchParams} The query.
 */
export function existingDataQuery(points, unit, sourceId) {
  const range = rangeOfPoints(points);
  const query = new URLSearchParams({
    start: isoInstant(range.start.getTime()),
    duration: formatIsoDuration(range.end - range.start),
    unit: unit,
  });
  if (sourceId !== null && sourceId !== undefined) query.set("source", String(sourceId));
  return query;
}

/**
 * Pair each existing value with the value to save that overlaps it in time.
 *
 * @param {Object[]} newPoints - The slots to save, sorted by start.
 * @param {Object[]} existingPoints - The existing slots, sorted by start.
 * @returns {{start: Date, end: Date, existing: number, proposed: number}[]} The existing slots that are overlapped.
 */
export function findOverlaps(newPoints, existingPoints) {
  const overlaps = [];
  let i = 0;
  for (const existing of existingPoints) {
    while (i < newPoints.length && newPoints[i].end <= existing.start) i++;
    const proposed = newPoints[i];
    if (proposed && proposed.start < existing.end) {
      overlaps.push({ start: existing.start, end: existing.end, existing: existing.value, proposed: proposed.value });
    }
  }
  return overlaps;
}

/**
 * Split the existing values that the values to save overlap by whose they are.
 *
 * New values supersede the user's own earlier values (they come from the same data source),
 * while values from other sources, such as a meter, stay alongside them.
 *
 * @param {Object[]} newPoints - The slots to save, sorted by start.
 * @param {Object[]} ownPoints - The user's own existing slots, sorted by start.
 * @param {Object[]} allPoints - The existing slots of all sources, sorted by start.
 * @returns {{own: Object[], others: Object[]}} The overlapped slots, as from findOverlaps.
 */
export function splitOverlapsBySource(newPoints, ownPoints, allPoints) {
  const own = findOverlaps(newPoints, ownPoints);
  const ownStarts = new Set(own.map((o) => o.start.getTime()));
  const others = findOverlaps(newPoints, allPoints).filter((o) => !ownStarts.has(o.start.getTime()));
  return { own: own, others: others };
}

/**
 * A regular series to save without the values that would update existing ones, to keep those and only fill the gaps.
 *
 * @param {Object} series - A body in the shape of posted sensor data.
 * @param {Object[]} overlaps - The existing slots it overlaps, from findOverlaps.
 * @param {number} resolutionMs - The sensor's event resolution, in milliseconds.
 * @returns {Object} The body, with null where values already exist.
 */
export function keepExisting(series, overlaps, resolutionMs) {
  const values = series.values.slice();
  const t0 = Date.parse(series.start);
  for (const overlap of overlaps) {
    const i = (overlap.start.getTime() - t0) / resolutionMs;
    if (Number.isInteger(i) && i >= 0 && i < values.length) values[i] = null;
  }
  return { ...series, values: values };
}

/**
 * The time range the slots cover.
 *
 * @param {Object[]} points - Slots, sorted by start.
 * @returns {{start: Date, end: Date}|null} The range, or null without slots.
 */
export function rangeOfPoints(points) {
  if (points.length === 0) return null;
  return { start: new Date(points[0].start), end: new Date(points[points.length - 1].end) };
}

const plural = (n, word) => n.toLocaleString() + " " + word + (n === 1 ? "" : "s");

function defaultFormatDate(isoDate) {
  return new Date(isoDate + "T00:00:00Z").toLocaleDateString(undefined, {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  });
}

/**
 * A warning about what one clock change does to the values to save, or null when it affects none of them.
 *
 * @param {Object} transition - A transition from the preview's report.
 * @param {Object} [options]
 * @param {function(string): string} [options.formatDate] - How a date such as "2026-10-25" is shown.
 * @returns {string|null} The warning.
 */
export function transitionWarning(transition, options) {
  const format = (options && options.formatDate) || defaultFormatDate;
  const day = format(transition.date);
  const hours = transition["wall-clock-start"] + "–" + transition["wall-clock-end"];
  if (transition.kind === "spring-forward") {
    const parts = [];
    if (transition["n-omitted"] > 0) parts.push(`${plural(transition["n-omitted"], "value")} will not be written`);
    if (transition["n-shifted"] > 0) {
      parts.push(`${plural(transition["n-shifted"], "value")} will start at ${transition["wall-clock-end"]}, when the clock resumes`);
    }
    return parts.length > 0 ? `On ${day} the clock skips ${hours}: ${parts.join(", and ")}.` : null;
  }
  if (transition.kind === "fall-back" && transition["n-duplicated"] > 0) {
    const n = transition["n-duplicated"];
    const those = n === 1 ? "that value" : `those ${n.toLocaleString()} values`;
    return `On ${day} ${hours} occurs twice: ${those} will be written to both.`;
  }
  return null;
}

/**
 * Why draft values cannot be repeated by the local clock, or null when they can.
 *
 * When the clocks go back, an hour occurs twice, and draft values covering both runs of it hold two values per local time.
 * Repeated, those would fall on the same local time, so the recurrence preview endpoint refuses them;
 * this explains that in terms of the draft values, before asking it.
 *
 * @param {{start: Date, end: Date, value: number}[]} drafts - The draft values, sorted by start.
 * @param {string} timeZone - The sensor's timezone.
 * @param {Object} [options]
 * @param {function(string): string} [options.formatDate] - How a date such as "2026-10-25" is shown.
 * @returns {string|null} The explanation.
 */
export function repeatedHourProblem(drafts, timeZone, options) {
  const format = (options && options.formatDate) || defaultFormatDate;
  const clock = new Intl.DateTimeFormat("en-GB", { timeZone: timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const seen = new Set();
  const twice = [];
  for (const draft of drafts) {
    const localTime = localDate(draft.start, timeZone) + " " + clock.format(draft.start);
    if (seen.has(localTime)) twice.push(draft);
    seen.add(localTime);
  }
  if (twice.length === 0) return null;
  const hours = clock.format(twice[0].start) + "–" + clock.format(twice[twice.length - 1].end);
  const day = format(localDate(twice[0].start, timeZone));
  return (
    `Your draft values cover ${hours} on ${day} twice, because the clocks go back an hour that night. ` +
    "Repeated, both would land on the same local time, so they cannot be repeated. " +
    "Remove the draft values of one of the two runs of that hour, or choose Do not repeat."
  );
}

// The local wall-clock time of an instant, as milliseconds since 1970 read as if the timezone were UTC.
function wallClockMs(date, timeZone) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timeZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(date);
  const part = (type) => Number(parts.find((p) => p.type === type).value);
  return Date.UTC(part("year"), part("month") - 1, part("day"), part("hour"), part("minute"));
}

const REPEAT_PHRASES = {
  daily: "every day",
  workdays: "on workdays",
  weekends: "on weekend days",
  "same-weekday": "every week",
};

/**
 * Why draft values are too long to be repeated as chosen, or null when they fit.
 *
 * Repeated every day (or on some days), draft values may span at most one day of local time, and repeated every week, one week.
 * The server refuses longer ones; this explains that in terms of the draft values, before asking it.
 *
 * @param {{start: Date, end: Date}[]} drafts - The draft values, sorted by start.
 * @param {string} repeat - One of REPEAT_CHOICES other than "none".
 * @param {string} timeZone - The sensor's timezone.
 * @param {Object} [options]
 * @param {function(Date): string} [options.formatTime] - How times are shown.
 * @returns {string|null} The explanation.
 */
export function patternTooLongProblem(drafts, repeat, timeZone, options) {
  const formatTime = (options && options.formatTime) || ((date) => date.toLocaleString());
  const weekly = repeat === "same-weekday";
  const periodMs = (weekly ? 7 : 1) * 24 * 3600 * 1000;
  const first = drafts[0];
  const last = drafts[drafts.length - 1];
  const spanMs = wallClockMs(last.end, timeZone) - wallClockMs(first.start, timeZone);
  if (spanMs <= periodMs) return null;
  const hours = Math.round(spanMs / 3600000);
  const span = hours < 48 ? plural(hours, "hour") : plural(Math.floor(hours / 24), "day") + (hours % 24 ? " and " + plural(hours % 24, "hour") : "");
  return (
    `Your draft values span ${span}, from ${formatTime(first.start)} until ${formatTime(last.end)}. ` +
    `To repeat them ${REPEAT_PHRASES[repeat]}, they can span at most one ${weekly ? "week" : "day"}. ` +
    (weekly ? "Remove some draft values, or choose Do not repeat." : "Remove some draft values, or choose Every week.")
  );
}

/**
 * The counts and warnings to show for a preview.
 *
 * @param {Object|null} report - The dry run's report, or null when the draft values are not repeated.
 * @param {number} patternCount - The number of draft values, which are all saved when they are not repeated.
 * @param {Object} [options] - Passed on to transitionWarning.
 * @param {Date} [options.patternStart] - When the draft values start, to name their weekday if the repeat days leave them out.
 * @param {string} [options.timeZone] - The sensor's timezone, for that weekday.
 * @returns {{toCreate: number, omitted: number, duplicated: number, patternIncluded: boolean, warnings: string[]}} The summary.
 */
export function summarizePreview(report, patternCount, options) {
  if (!report) return { toCreate: patternCount, omitted: 0, duplicated: 0, patternIncluded: true, warnings: [] };
  const warnings = report.transitions.map((t) => transitionWarning(t, options)).filter(Boolean);
  const patternIncluded = report["pattern-included"] !== false;
  if (!patternIncluded) warnings.unshift(patternLeftOutMessage(patternCount, options) + " Only their repeats are saved.");
  return {
    toCreate: report["n-values"],
    omitted: report["n-omitted"],
    duplicated: report["n-duplicated"],
    patternIncluded: patternIncluded,
    warnings: warnings,
  };
}

// Why the draft values themselves are not saved: the repeat days leave out the day they fall on.
function patternLeftOutMessage(patternCount, options) {
  const opts = options || {};
  const weekday = opts.patternStart
    ? opts.patternStart.toLocaleDateString("en-GB", { weekday: "long", timeZone: opts.timeZone })
    : null;
  const those = patternCount === 1 ? "Your draft value falls" : `Your ${patternCount.toLocaleString()} draft values fall`;
  return weekday ? `${those} on a ${weekday}, outside the repeat days.` : `${those} outside the repeat days.`;
}

/**
 * Call the API and read its JSON answer, also when it refuses.
 *
 * @param {string} url - The URL.
 * @param {RequestInit} [init] - As for fetch.
 * @returns {Promise<{ok: boolean, status: number, body: any}>} The answer.
 */
export async function requestJson(url, init) {
  const response = await fetch(url, init);
  let body = null;
  try {
    body = await response.json();
  } catch (e) {
    body = null;
  }
  return { ok: response.ok, status: response.status, body: body };
}

// The API's message for a refused request, as plain text (extractApiErrorMessage marks field names up in HTML).
export function errorText(answer) {
  const message = extractApiErrorMessage(answer.body, "The request failed (" + answer.status + ").");
  return message.replace(/<\/?b>/g, "").replace(/\s+/g, " ").trim();
}

/**
 * Wire the preview step of the "Draft values" panel.
 *
 * The step's elements are found by their data attributes inside the root:
 * data-preview-summary (describes the draft values), data-preview-repeat (a select with an option per REPEAT_CHOICES),
 * data-preview-until-group (shown when repeating), holding data-preview-until (a date field),
 * data-preview-error (an inline alert), data-preview-run (runs a failed preview again),
 * data-preview-busy (shown while previewing),
 * data-preview-result (shown once previewed), holding data-preview-create, -omitted, -duplicated, -superseded and -alongside (counts),
 * data-preview-warnings (a list), data-preview-show-all and data-preview-show-drafts (zoom links),
 * and data-preview-back, data-preview-discard and data-preview-confirm.
 *
 * The step opens on the hand-off of the draft values (DRAFT_VALUES_RECORDED_EVENT), when there are any, and previews them;
 * a hand-off to save them as they are saves them without showing the step.
 *
 * @param {HTMLElement} root - The step.
 * @param {Object} options
 * @param {number} options.sensorId - The sensor, whose hand-offs are picked up.
 * @param {number} options.resolutionMs - The sensor's event resolution, in milliseconds.
 * @param {string} options.unit - The sensor's unit.
 * @param {string} options.timeZone - The sensor's timezone.
 * @param {number|null} [options.sourceId] - The user's own data source, whose earlier values new ones update, if they have one yet.
 * @param {Object} options.api - The requests, each resolving to {ok, status, body} (see requestJson):
 *   preview(body) for a dry run of POST /sensors/<id>/data, fetchExisting(query) and save(payload).
 * @param {Object} options.chart - How the step drives the chart:
 *   showPreview({points, superseded}|null), getWindow() and setWindow(range) for the visible time range, and reload().
 * @param {Object} options.drafts - The draft step: discard() clears the draft values without asking.
 * @param {function(boolean, Object)} options.setVisible - Shows this step instead of the draft step, or the other way around;
 *   with {keepOpen: true}, the panel stays open on the draft step, as the user goes back to edit the draft values on the chart.
 * @param {function(string): boolean} [options.confirm] - Asks the user to confirm (window.confirm by default).
 * @param {function(string, string, Object)} [options.notify] - Shows a message (which may hold a link), its type and showToast's options (showToast by default).
 * @param {EventTarget} [options.target] - Where the hand-off arrives (document by default).
 * @param {function(Date): string} [options.formatTime] - How times are shown.
 * @param {function(string): string} [options.formatDate] - How dates such as "2026-10-25" are shown in warnings.
 * @returns {Object} The step's controller.
 */
export function wirePreviewStep(root, options) {
  const opts = Object.assign(
    {
      confirm: (message) => window.confirm(message),
      notify: showToastIfAvailable,
      target: document,
      formatTime: (date) => date.toLocaleString(undefined, {
        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short",
      }),
      formatDate: defaultFormatDate,
    },
    options,
  );
  const el = (name) => root.querySelector("[data-preview-" + name + "]");
  const repeatField = el("repeat");
  const untilInput = el("until");
  const runButton = el("run");
  const busyNote = el("busy");
  const errorBox = el("error");
  const resultBox = el("result");
  const warningList = el("warnings");
  const confirmButton = el("confirm");

  let open = false;
  let drafts = [];
  let result = null;
  let error = "";
  let canRetry = false;
  // Busy previewing, which a new choice may interrupt; saving may not be interrupted.
  let busy = false;
  let saving = false;
  // The window shown before the preview zoomed, to go back to.
  let windowBefore = null;
  // Draft values that the repeat days left out of the last save, which the user may still save.
  let leftOut = null;
  // Each run, and each change that makes a run out of date, takes a new number, so a late answer is ignored.
  let run = 0;

  const repeat = () => repeatField.value || "none";
  const existingField = el("existing");
  const keepingExisting = () => !!existingField && existingField.value === "keep";

  // What Confirm saves: the previewed request as it is, or, to keep the user's earlier values, the previewed values except those.
  function toSave() {
    const keep = keepingExisting() && result.overlaps.length > 0;
    if (!keep) {
      return { payloads: [result.body], points: result.points, superseded: result.overlaps, count: result.summary.toCreate };
    }
    const kept = new Set(result.overlaps.map((o) => o.start.getTime()));
    return {
      payloads: result.chunks.map((chunk) => keepExisting(chunk, result.overlaps, opts.resolutionMs)),
      points: result.points.filter((p) => !kept.has(p.start.getTime())),
      superseded: [],
      count: result.summary.toCreate - result.overlaps.length,
    };
  }

  function render() {
    const count = drafts.length;
    el("summary").textContent = count === 0 ? "" :
      plural(count, "draft value") + ", from " + opts.formatTime(drafts[0].start) + " until " + opts.formatTime(drafts[count - 1].end) + ".";
    el("until-group").classList.toggle("d-none", repeat() === "none");
    untilInput.disabled = saving || repeat() === "none";
    repeatField.disabled = saving;
    errorBox.textContent = error;
    errorBox.classList.toggle("d-none", !error);
    runButton.classList.toggle("d-none", !error || !canRetry || !!result);
    busyNote.classList.toggle("d-none", !busy);
    resultBox.classList.toggle("d-none", !result);
    const saved = result ? toSave() : null;
    confirmButton.disabled = busy || saving || !result || saved.count === 0;
    // Say what Confirm does, once the preview tells how much.
    confirmButton.textContent = !saved ? "Save" : saved.count === 0 ? "Nothing new to save" : "Save " + plural(saved.count, "value");
    for (const link of [el("back"), el("discard")]) {
      link.classList.toggle("pe-none", saving);
      link.setAttribute("aria-disabled", saving ? "true" : "false");
    }
    if (result) {
      const { summary, overlaps, others } = result;
      el("create").textContent = saved.count.toLocaleString();
      el("omitted").textContent = summary.omitted.toLocaleString();
      el("duplicated").textContent = summary.duplicated.toLocaleString();
      el("superseded").textContent = overlaps.length.toLocaleString();
      const rows = [["omitted", summary.omitted], ["duplicated", summary.duplicated], ["superseded", overlaps.length]];
      if (el("alongside")) {
        el("alongside").textContent = others.length.toLocaleString();
        rows.push(["alongside", others.length]);
      }
      // Rows that do not apply would only add noise.
      for (const [name, n] of rows) {
        el(name).parentElement.classList.toggle("d-none", n === 0);
      }
      // The choice about the user's earlier values only matters when there are some; values from other sources stay anyway.
      if (existingField) {
        el("existing-group").classList.toggle("d-none", overlaps.length === 0);
        existingField.disabled = saving;
        el("superseded-label").textContent = keepingExisting() ? "Your earlier values, kept" : "Updating your earlier values";
      }
      warningList.replaceChildren(
        ...summary.warnings.map((warning) => {
          const item = document.createElement("li");
          item.textContent = warning;
          return item;
        }),
      );
      warningList.classList.toggle("d-none", summary.warnings.length === 0);
    }
  }

  // Draw what Confirm would save, and what it would replace.
  function showOnChart() {
    const saved = toSave();
    opts.chart.showPreview({ points: saved.points, superseded: saved.superseded });
  }

  // A choice changed, so the preview no longer shows what would be saved.
  function invalidate() {
    run++;
    busy = false;
    error = "";
    if (result) opts.chart.showPreview(null);
    result = null;
  }

  function setUntilBounds() {
    if (repeat() === "none" || drafts.length === 0) return;
    const bounds = untilBounds(drafts, opts.timeZone, repeat());
    untilInput.min = bounds.min;
    untilInput.max = bounds.max;
    if (!untilInput.value || untilInput.value < bounds.min || untilInput.value > bounds.max) {
      untilInput.value = bounds.default;
    }
  }

  // Show this range on the chart, remembering the window shown before the preview first zoomed, for Back.
  function zoomTo(range) {
    if (!range) return;
    if (!windowBefore) windowBefore = opts.chart.getWindow();
    opts.chart.setWindow(range);
  }

  function close(restoreWindow, keepOpen) {
    invalidate();
    if (restoreWindow && windowBefore) opts.chart.setWindow(windowBefore);
    windowBefore = null;
    open = false;
    opts.setVisible(false, { keepOpen: !!keepOpen });
  }

  const controller = {
    get open() {
      return open;
    },
    get result() {
      return result;
    },
    get error() {
      return error;
    },
    // Show the step for these draft values, starting from no repetition, and preview them.
    show(handedOver) {
      if (!handedOver || handedOver.length === 0) return;
      invalidate();
      drafts = handedOver.map((d) => ({ start: new Date(d.start), end: new Date(d.end), value: d.value }));
      repeatField.value = "none";
      if (existingField) existingField.value = "replace";
      // Name the weekday, so "every week" says which day.
      const weekly = repeatField.querySelector('option[value="same-weekday"]');
      if (weekly) {
        weekly.textContent = "Every week on " + drafts[0].start.toLocaleDateString("en-GB", { weekday: "long", timeZone: opts.timeZone });
      }
      untilInput.value = "";
      open = true;
      opts.setVisible(true);
      render();
      controller.preview();
    },
    // Fetch what would be saved, and show it.
    async preview() {
      if (!open || saving) return;
      invalidate();
      const thisRun = run;
      const chosen = repeat();
      const until = untilInput.value;
      // Only a failure that may pass, such as a lost connection, is offered to run again.
      const fail = (message, retry) => {
        if (thisRun !== run) return;
        error = message;
        canRetry = !!retry;
        busy = false;
        render();
      };
      if (chosen !== "none") {
        const bounds = untilBounds(drafts, opts.timeZone, chosen);
        if (!until || until < bounds.min || until > bounds.max) {
          return fail("Choose a date to repeat until, from " + bounds.min + " to " + bounds.max + ".");
        }
        const problem =
          patternTooLongProblem(drafts, chosen, opts.timeZone, { formatTime: opts.formatTime }) ||
          repeatedHourProblem(drafts, opts.timeZone, { formatDate: opts.formatDate });
        if (problem) return fail(problem);
      }
      busy = true;
      render();
      try {
        const pattern = draftsToPattern(drafts, opts.resolutionMs, opts.unit);
        let report = null;
        let body = pattern;
        let chunks = [pattern];
        if (chosen !== "none") {
          // The same request saves the values later, without the dry run, so the server saves what it previews here.
          body = repeatRequestBody(pattern, chosen, until);
          const answer = await opts.api.preview(body);
          if (thisRun !== run) return;
          if (!answer.ok) return fail(errorText(answer), answer.status === 0 || answer.status >= 500);
          chunks = answer.body.data;
          report = answer.body.report;
        }
        const points = chunksToPoints(chunks, opts.resolutionMs);
        const [allAnswer, ownAnswer] = await Promise.all([
          opts.api.fetchExisting(existingDataQuery(points, opts.unit)),
          opts.sourceId === null || opts.sourceId === undefined
            ? Promise.resolve(null)
            : opts.api.fetchExisting(existingDataQuery(points, opts.unit, opts.sourceId)),
        ]);
        if (thisRun !== run) return;
        for (const existingAnswer of [allAnswer, ownAnswer]) {
          if (existingAnswer && !existingAnswer.ok) {
            return fail("The existing data could not be loaded to compare with: " + errorText(existingAnswer), true);
          }
        }
        const existing = splitOverlapsBySource(
          points,
          ownAnswer ? gridToPoints(ownAnswer.body, opts.resolutionMs) : [],
          gridToPoints(allAnswer.body, opts.resolutionMs),
        );
        result = {
          body: body,
          chunks: chunks,
          points: points,
          overlaps: existing.own,
          others: existing.others,
          summary: summarizePreview(report, drafts.length, {
            formatDate: opts.formatDate, patternStart: drafts[0].start, timeZone: opts.timeZone,
          }),
        };
        busy = false;
        showOnChart();
        // Repeats may reach far beyond the window shown, and without them, the draft values are what will be saved.
        if (chosen !== "none") controller.showAll();
        else controller.showDrafts();
        render();
      } catch (e) {
        if (e instanceof PreviewError) return fail(e.message);
        fail("The preview failed: " + e.message, true);
      }
    },
    // Zoom out to everything that would be saved.
    showAll() {
      if (!result) return;
      zoomTo(rangeOfPoints(result.points));
    },
    // Zoom in to the draft values.
    showDrafts() {
      zoomTo(rangeOfPoints(drafts));
    },
    // Go back to the draft step, with the draft values as they were, keeping the panel open to edit them.
    back() {
      if (saving) return;
      close(true, true);
    },
    // Discard the draft values, after confirmation.
    discard() {
      if (saving) return;
      if (!opts.confirm("Discard " + plural(drafts.length, "draft value") + "? They have not been saved.")) return;
      opts.drafts.discard();
      close(true);
    },
    // Save draft values as they are, without showing the step; a refusal is told in a toast, and keeps the draft values.
    async saveAsIs(handedOver) {
      if (!handedOver || handedOver.length === 0 || open || saving) return;
      const slots = handedOver.map((d) => ({ start: new Date(d.start), end: new Date(d.end), value: d.value }));
      let payload;
      try {
        payload = draftsToPattern(slots, opts.resolutionMs, opts.unit);
      } catch (e) {
        opts.notify(e instanceof PreviewError ? e.message : "Nothing was saved: " + e.message, "error");
        return;
      }
      saving = true;
      let answer;
      try {
        answer = await opts.api.save(payload);
      } catch (e) {
        answer = { ok: false, status: 0, body: { message: e.message } };
      }
      saving = false;
      if (!answer.ok) {
        opts.notify("Nothing was saved: " + errorText(answer), "error");
        return;
      }
      opts.notify(savedMessage(answer), "success");
      opts.drafts.discard();
      opts.chart.reload();
    },
    // Save what the preview shows, unchanged.
    async save() {
      if (!result || busy || saving) return;
      const thisRun = run;
      saving = true;
      render();
      const { payloads } = toSave();
      let answer;
      let nSaved = 0;
      for (const payload of payloads) {
        try {
          answer = await opts.api.save(payload);
        } catch (e) {
          answer = { ok: false, status: 0, body: { message: e.message } };
        }
        if (!answer.ok) break;
        nSaved++;
      }
      saving = false;
      if (thisRun !== run) return;
      if (!answer.ok) {
        error = (nSaved === 0 ? "Nothing was saved: " : "Only part of the values was saved: ") + errorText(answer);
        render();
        return;
      }
      const patternLeftOut = !result.summary.patternIncluded;
      const savedDrafts = drafts;
      opts.notify(savedMessage(answer), "success");
      if (patternLeftOut) {
        leftOut = savedDrafts;
        opts.notify(
          patternLeftOutMessage(savedDrafts.length, { patternStart: savedDrafts[0].start, timeZone: opts.timeZone }) +
            ' They were not saved. <a href="#" class="link-light" data-draft-save-left-out>Save them too</a>',
          "info",
          { delay: 15000 },
        );
      }
      opts.drafts.discard();
      close(false);
      opts.chart.reload();
    },
    // Save the draft values that the repeat days left out of the last save, as they are.
    async saveLeftOut() {
      if (!leftOut) return;
      const handedOver = leftOut;
      leftOut = null;
      await controller.saveAsIs(handedOver);
    },
  };

  // Keeping or replacing existing values changes what is saved, not the preview, so it needs no new one.
  if (existingField) {
    existingField.addEventListener("change", () => {
      if (!result) return;
      showOnChart();
      render();
    });
  }
  repeatField.addEventListener("change", () => {
    invalidate();
    setUntilBounds();
    render();
    controller.preview();
  });
  untilInput.addEventListener("change", () => {
    invalidate();
    render();
    controller.preview();
  });
  // These are links, like the secondary actions of the other panels.
  const onLink = (name, action) => el(name).addEventListener("click", (event) => {
    event.preventDefault();
    action();
  });
  onLink("run", () => controller.preview());
  onLink("show-all", () => controller.showAll());
  onLink("show-drafts", () => controller.showDrafts());
  onLink("back", () => controller.back());
  onLink("discard", () => controller.discard());
  confirmButton.addEventListener("click", () => controller.save());
  // The link in the toast about left-out draft values; toasts live outside the panel.
  document.addEventListener("click", (event) => {
    const link = event.target && event.target.closest && event.target.closest("[data-draft-save-left-out]");
    if (!link) return;
    event.preventDefault();
    controller.saveLeftOut();
  });
  opts.target.addEventListener(DRAFT_VALUES_RECORDED_EVENT, (event) => {
    if (!event.detail || event.detail.sensorId !== opts.sensorId) return;
    if (event.detail.action === "save") controller.saveAsIs(event.detail.drafts);
    else controller.show(event.detail.drafts);
  });

  render();
  return controller;
}

// A 202 means the values are saved in the background.
function savedMessage(answer) {
  return answer.status === 202 ? "Saved, values will appear shortly." : "Saved.";
}

function showToastIfAvailable(message, type, options) {
  if (typeof showToast === "function") showToast(message, type, options);
}
