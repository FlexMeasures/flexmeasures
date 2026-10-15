/**
 * Preview and confirm draft sensor values before saving them (#2469), the second step of the "Draft values" panel.
 *
 * The user chooses whether to repeat the draft values (daily, or on the same weekday only) and until when.
 * Repeats come from the recurrence preview endpoint (POST /sensors/<id>/data/preview-recurrence),
 * which resolves daylight saving time transitions and reports what they did.
 * The preview shows what will be saved on the chart, with the existing values it supersedes,
 * and Confirm saves it through POST /sensors/<id>/data.
 *
 * The pure functions build the requests and read their answers; wirePreviewStep connects them to the panel.
 * Values are kept as slots: { start: Date, end: Date, value: number }, like draft values.
 */

import { DRAFT_VALUES_RECORDED_EVENT, formatIsoDuration } from "./draft-values.js";
import { extractApiErrorMessage } from "./ui-utils.js";

// The repeat choices, as the recurrence preview endpoint names them ("none" means saving the draft values only).
export const REPEAT_CHOICES = ["none", "daily", "same-weekday"];

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
 * and the latest is one year after they start, the cap of the recurrence preview endpoint.
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
 * The body for the recurrence preview endpoint.
 *
 * @param {Object} pattern - A pattern from draftsToPattern.
 * @param {string} repeat - "daily" or "same-weekday".
 * @param {string} until - The last date to repeat on, e.g. "2026-11-01".
 * @returns {Object} The body.
 */
export function previewRequestBody(pattern, repeat, until) {
  return { ...pattern, values: pattern.values.slice(), repeat: repeat, until: until };
}

/**
 * The slots with a value in a regular series of values, such as the preview's data or a GET /sensors/data response.
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
 * The body for POST /sensors/data: the pattern, then null values up to the first repeat, then the repeats as previewed.
 *
 * The preview leaves out the pattern itself, so both are saved in one request,
 * which the API lays out in fixed steps from the pattern's start.
 *
 * @param {Object} pattern - A pattern from draftsToPattern.
 * @param {Object|null} previewData - The `data` of the preview response, or null to save the pattern only.
 * @param {number} resolutionMs - The sensor's event resolution, in milliseconds.
 * @returns {{start: string, duration: string, values: (number|null)[], unit: string}} The body.
 * @throws {PreviewError} When the repeats do not continue the pattern's fixed steps (daily slots across a clock change).
 */
export function payloadForSaving(pattern, previewData, resolutionMs) {
  if (!previewData) return { ...pattern, values: pattern.values.slice() };
  const patternEnd = Date.parse(pattern.start) + pattern.values.length * resolutionMs;
  const gap = (Date.parse(previewData.start) - patternEnd) / resolutionMs;
  if (!Number.isInteger(gap) || gap < 0) {
    throw new PreviewError(
      "The draft values and their repeats cannot be saved as one series of values, as a daylight saving time transition lies between them. " +
      "Draft the values on a day after the transition instead.",
    );
  }
  const values = pattern.values.concat(new Array(gap).fill(null), previewData.values);
  return { start: pattern.start, duration: formatIsoDuration(values.length * resolutionMs), values: values, unit: pattern.unit };
}

/**
 * The query for GET /sensors/data that loads the existing values over the same range as the values to save.
 *
 * @param {Object} payload - A body from payloadForSaving.
 * @param {string} unit - The unit to load the existing values in.
 * @returns {URLSearchParams} The query.
 */
export function existingDataQuery(payload, unit) {
  return new URLSearchParams({ start: payload.start, duration: payload.duration, unit: unit });
}

/**
 * Pair each existing value with the value to save that overlaps it in time.
 *
 * Kept apart on purpose: the preview highlights these as superseded,
 * and leaving out times that already have data (should that be chosen in #2255) would drop them from the body instead.
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
  const hours = transition.wall_clock_start + "–" + transition.wall_clock_end;
  if (transition.kind === "spring_forward" && transition.n_omitted > 0) {
    return `On ${day} the clock skips ${hours}: ${plural(transition.n_omitted, "value")} will not be written.`;
  }
  if (transition.kind === "fall_back" && transition.n_duplicated > 0) {
    const those = transition.n_duplicated === 1 ? "that value" : `those ${transition.n_duplicated.toLocaleString()} values`;
    return `On ${day} ${hours} occurs twice: ${those} will be written to both.`;
  }
  return null;
}

/**
 * The counts and warnings to show for a preview.
 *
 * @param {Object|null} report - The preview's report, or null when the draft values are not repeated.
 * @param {number} patternCount - The number of draft values, which the report does not count.
 * @param {Object} [options] - Passed on to transitionWarning.
 * @returns {{toCreate: number, omitted: number, duplicated: number, warnings: string[]}} The summary.
 */
export function summarizePreview(report, patternCount, options) {
  if (!report) return { toCreate: patternCount, omitted: 0, duplicated: 0, warnings: [] };
  const warnings = report.transitions.map((t) => transitionWarning(t, options)).filter(Boolean);
  if (report.fallback_reason) warnings.push(report.fallback_reason);
  return {
    toCreate: patternCount + report.n_values,
    omitted: report.n_omitted,
    duplicated: report.n_duplicated,
    warnings: warnings,
  };
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
 * data-preview-summary (describes the draft values), data-preview-repeat (one radio button per REPEAT_CHOICES),
 * data-preview-until (a date field), data-preview-run (the Preview button), data-preview-error (an inline alert),
 * data-preview-result (shown once previewed), holding data-preview-create, -omitted, -duplicated and -superseded (counts),
 * data-preview-warnings (a list), data-preview-show-all and data-preview-show-drafts (zoom buttons),
 * and data-preview-back, data-preview-discard and data-preview-confirm.
 *
 * The step opens on the hand-off of the draft values (DRAFT_VALUES_RECORDED_EVENT), when there are any.
 *
 * @param {HTMLElement} root - The step.
 * @param {Object} options
 * @param {number} options.sensorId - The sensor, whose hand-offs are picked up.
 * @param {number} options.resolutionMs - The sensor's event resolution, in milliseconds.
 * @param {string} options.unit - The sensor's unit.
 * @param {string} options.timeZone - The sensor's timezone.
 * @param {Object} options.api - The requests, each resolving to {ok, status, body} (see requestJson):
 *   preview(body), fetchExisting(query) and save(payload).
 * @param {Object} options.chart - How the step drives the chart:
 *   showPreview({points, superseded}|null), getWindow() and setWindow(range) for the visible time range, and reload().
 * @param {Object} options.drafts - The draft step: discard() clears the draft values without asking.
 * @param {function(boolean)} options.setVisible - Shows this step instead of the draft step, or the other way around.
 * @param {function(string): boolean} [options.confirm] - Asks the user to confirm (window.confirm by default).
 * @param {function(string, string)} [options.notify] - Shows a message and its type (showToast by default).
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
  const repeatInputs = Array.from(root.querySelectorAll("[data-preview-repeat]"));
  const untilInput = el("until");
  const runButton = el("run");
  const errorBox = el("error");
  const resultBox = el("result");
  const warningList = el("warnings");
  const confirmButton = el("confirm");

  let open = false;
  let drafts = [];
  let result = null;
  let error = "";
  let busy = false;
  // The window shown before the preview zoomed out, to go back to.
  let draftsWindow = null;
  // Each run, and each change that makes a run out of date, takes a new number, so a late answer is ignored.
  let run = 0;

  const repeat = () => (repeatInputs.find((input) => input.checked) || {}).value || "none";

  function render() {
    const count = drafts.length;
    el("summary").textContent = count === 0 ? "" :
      plural(count, "draft value") + ", from " + opts.formatTime(drafts[0].start) + " until " + opts.formatTime(drafts[count - 1].end) + ".";
    untilInput.disabled = busy || repeat() === "none";
    repeatInputs.forEach((input) => { input.disabled = busy; });
    runButton.disabled = busy;
    errorBox.textContent = error;
    errorBox.classList.toggle("d-none", !error);
    resultBox.classList.toggle("d-none", !result);
    confirmButton.disabled = busy || !result;
    el("back").disabled = el("discard").disabled = busy;
    if (result) {
      const { summary, overlaps } = result;
      el("create").textContent = summary.toCreate.toLocaleString();
      el("omitted").textContent = summary.omitted.toLocaleString();
      el("duplicated").textContent = summary.duplicated.toLocaleString();
      el("superseded").textContent = overlaps.length.toLocaleString();
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

  function close(restoreWindow) {
    invalidate();
    if (restoreWindow && draftsWindow) opts.chart.setWindow(draftsWindow);
    draftsWindow = null;
    open = false;
    opts.setVisible(false);
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
    // Show the step for these draft values, starting from no repetition.
    show(handedOver) {
      if (!handedOver || handedOver.length === 0) return;
      invalidate();
      drafts = handedOver.map((d) => ({ start: new Date(d.start), end: new Date(d.end), value: d.value }));
      repeatInputs.forEach((input) => { input.checked = input.value === "none"; });
      untilInput.value = "";
      open = true;
      opts.setVisible(true);
      render();
    },
    // Fetch what would be saved, and show it.
    async preview() {
      if (!open || busy) return;
      invalidate();
      const thisRun = run;
      const chosen = repeat();
      const until = untilInput.value;
      const fail = (message) => {
        if (thisRun !== run) return;
        error = message;
        busy = false;
        render();
      };
      if (chosen !== "none") {
        const bounds = untilBounds(drafts, opts.timeZone, chosen);
        if (!until || until < bounds.min || until > bounds.max) {
          return fail("Choose a date to repeat until, from " + bounds.min + " to " + bounds.max + ".");
        }
      }
      busy = true;
      render();
      try {
        const pattern = draftsToPattern(drafts, opts.resolutionMs, opts.unit);
        let report = null;
        let repeats = null;
        if (chosen !== "none") {
          const answer = await opts.api.preview(previewRequestBody(pattern, chosen, until));
          if (thisRun !== run) return;
          if (!answer.ok) return fail(errorText(answer));
          repeats = answer.body.data;
          report = answer.body.report;
        }
        const payload = payloadForSaving(pattern, repeats, opts.resolutionMs);
        const existingAnswer = await opts.api.fetchExisting(existingDataQuery(payload, opts.unit));
        if (thisRun !== run) return;
        if (!existingAnswer.ok) {
          return fail("The existing data could not be loaded to compare with: " + errorText(existingAnswer));
        }
        const points = gridToPoints(payload, opts.resolutionMs);
        const overlaps = findOverlaps(points, gridToPoints(existingAnswer.body, opts.resolutionMs));
        result = {
          payload: payload,
          points: points,
          overlaps: overlaps,
          summary: summarizePreview(report, drafts.length, { formatDate: opts.formatDate }),
        };
        busy = false;
        opts.chart.showPreview({ points: points, superseded: overlaps });
        controller.showAll();
        render();
      } catch (e) {
        if (e instanceof PreviewError) return fail(e.message);
        fail("The preview failed: " + e.message);
      }
    },
    // Zoom out to everything that would be saved.
    showAll() {
      if (!result) return;
      if (!draftsWindow) draftsWindow = opts.chart.getWindow();
      opts.chart.setWindow(rangeOfPoints(result.points));
    },
    // Zoom back to the window shown before the preview.
    showDrafts() {
      if (draftsWindow) opts.chart.setWindow(draftsWindow);
    },
    // Go back to the draft step, with the draft values as they were.
    back() {
      if (busy) return;
      close(true);
    },
    // Discard the draft values, after confirmation.
    discard() {
      if (busy) return;
      if (!opts.confirm("Discard " + plural(drafts.length, "draft value") + "? They have not been saved.")) return;
      opts.drafts.discard();
      close(true);
    },
    // Save what the preview shows, unchanged.
    async save() {
      if (!result || busy) return;
      const thisRun = run;
      busy = true;
      render();
      let answer;
      try {
        answer = await opts.api.save(result.payload);
      } catch (e) {
        answer = { ok: false, status: 0, body: { message: e.message } };
      }
      if (thisRun !== run) return;
      busy = false;
      if (!answer.ok) {
        error = "Nothing was saved: " + errorText(answer);
        render();
        return;
      }
      // A 202 means the values are saved in the background.
      opts.notify(answer.status === 202 ? "Saved, values will appear shortly." : "Saved.", "success");
      opts.drafts.discard();
      close(false);
      opts.chart.reload();
    },
  };

  repeatInputs.forEach((input) =>
    input.addEventListener("change", () => {
      invalidate();
      setUntilBounds();
      render();
    }),
  );
  untilInput.addEventListener("change", () => {
    invalidate();
    render();
  });
  runButton.addEventListener("click", () => controller.preview());
  el("show-all").addEventListener("click", () => controller.showAll());
  el("show-drafts").addEventListener("click", () => controller.showDrafts());
  el("back").addEventListener("click", () => controller.back());
  el("discard").addEventListener("click", () => controller.discard());
  confirmButton.addEventListener("click", () => controller.save());
  opts.target.addEventListener(DRAFT_VALUES_RECORDED_EVENT, (event) => {
    if (event.detail && event.detail.sensorId === opts.sensorId) controller.show(event.detail.drafts);
  });

  render();
  return controller;
}

function showToastIfAvailable(message, type) {
  if (typeof showToast === "function") showToast(message, type);
}
