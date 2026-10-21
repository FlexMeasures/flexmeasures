/**
 * Draft sensor values, created on the sensor graph before anything is saved (#2468).
 *
 * A draft value covers one event (slot) of a sensor: { start: Date, end: Date, value: number }.
 * Lists of draft values are kept sorted by start, and are never changed in place.
 *
 * The pure functions turn a selection on the chart into slots, and fill, replace and remove draft values.
 * wireDraftValuesPanel connects them to the "Draft values" side panel on the sensor page.
 * Nothing here writes to the database: handOver hands the draft values over in a DRAFT_VALUES_RECORDED_EVENT,
 * for the preview step (#2469) to save them as they are, or to preview them first.
 */

import { snapRangeToEvents } from "./chart-data-utils.js";

const DAY_MS = 24 * 60 * 60 * 1000;

// More slots than this in one selection would make the panel's list unwieldy, so such a selection is refused.
export const MAX_DRAFT_SLOTS = 2000;

// Fired on the panel's event target when the user moves on to save or preview, with { sensorId, drafts, action } as detail,
// where action is "save" (as they are) or "preview".
export const DRAFT_VALUES_RECORDED_EVENT = "draftvaluesrecorded";

/**
 * The slots (whole events) a selection on the chart covers.
 *
 * The selection is widened to whole events on the grid through the anchor (see snapRangeToEvents),
 * so a click (a selection whose start equals its end) becomes the event it lies in.
 * Daily events step along the local calendar, so a day with a DST transition is one 23- or 25-hour slot.
 *
 * @param {{start: Date, end: Date}|null} range - The selection.
 * @param {number} resolutionMs - The sensor's event resolution, in milliseconds.
 * @param {number} anchorMs - Any event start, in milliseconds since the epoch.
 * @returns {{start: Date, end: Date}[]} The slots, in order; none for an instantaneous sensor or no selection.
 */
export function selectionToSlots(range, resolutionMs, anchorMs) {
  if (!range || !(resolutionMs > 0)) return [];
  const snapped = snapRangeToEvents(range, resolutionMs, anchorMs);
  const slots = [];
  let start = snapped.start;
  while (start < snapped.end) {
    let end;
    if (resolutionMs === DAY_MS) {
      end = new Date(start);
      end.setDate(end.getDate() + 1);
    } else {
      end = new Date(start.getTime() + resolutionMs);
    }
    slots.push({ start: start, end: end });
    start = end;
  }
  return slots;
}

/**
 * Give every slot a draft value, replacing the draft values it overlaps.
 *
 * Overlap, rather than an equal start, decides what is replaced,
 * so that a draft value made on a shifted grid (e.g. after new data moved the anchor) cannot end up doubled.
 *
 * @param {Object[]} drafts - The current draft values.
 * @param {{start: Date, end: Date}[]} slots - The slots to fill.
 * @param {number} value - The value to give them.
 * @returns {Object[]} The new draft values, sorted by start.
 */
export function fillSlots(drafts, slots, value) {
  return mergeDrafts(drafts, slots.map((slot) => ({ start: slot.start, end: slot.end, value: value })));
}

/**
 * Add draft values, each replacing what it overlaps.
 *
 * @param {Object[]} drafts - The current draft values.
 * @param {Object[]} values - The draft values to add, e.g. from fillSlots or strokeToDrafts.
 * @returns {Object[]} The new draft values, sorted by start.
 */
export function mergeDrafts(drafts, values) {
  const added = values.map((slot) => ({ start: new Date(slot.start), end: new Date(slot.end), value: slot.value }));
  const overlapsAdded = (draft) => added.some((slot) => draft.start < slot.end && slot.start < draft.end);
  return drafts
    .filter((draft) => !overlapsAdded(draft))
    .concat(added)
    .sort((a, b) => a.start - b.start);
}

/**
 * Remove the draft value starting at the given time.
 *
 * @param {Object[]} drafts - The current draft values.
 * @param {number} startMs - The start of the draft value to remove, in milliseconds since the epoch.
 * @returns {Object[]} The remaining draft values.
 */
export function removeDraft(drafts, startMs) {
  return drafts.filter((draft) => draft.start.getTime() !== startMs);
}

/**
 * The draft values a stroke drawn on the chart makes: one per slot it crosses, with the stroke's height there.
 *
 * Each slot takes the value where the stroke passes its middle, interpolated between the drawn points,
 * and where the stroke passes it more than once, the last pass counts.
 * A slot the stroke only touches at an end, or a click, takes the value of the nearest point.
 * Values are rounded to the step, the finest one the drawing can tell apart (see drawnValueStep in fast-chart.js).
 *
 * @param {{time: Date, value: number}[]} points - The points of the stroke, in the order drawn.
 * @param {number} resolutionMs - The sensor's event resolution, in milliseconds.
 * @param {number} anchorMs - Any event start, in milliseconds since the epoch.
 * @param {number} [step] - The step to round values to; values are kept as drawn without one.
 * @returns {{start: Date, end: Date, value: number}[]} The draft values, sorted by start.
 */
export function strokeToDrafts(points, resolutionMs, anchorMs, step) {
  if (!points || points.length === 0) return [];
  const times = points.map((point) => point.time.getTime());
  const range = { start: new Date(Math.min(...times)), end: new Date(Math.max(...times)) };
  const decimals = step > 0 ? Math.max(0, -Math.floor(Math.log10(step))) : null;
  const round = (value) => (decimals === null ? value : Number((Math.round(value / step) * step).toFixed(decimals)));
  return selectionToSlots(range, resolutionMs, anchorMs).map((slot) => ({
    start: slot.start,
    end: slot.end,
    value: round(strokeValueAt(points, (slot.start.getTime() + slot.end.getTime()) / 2)),
  }));
}

// The height of a stroke at a time: on the last drawn segment that spans it, or else at the nearest point.
function strokeValueAt(points, t) {
  for (let k = points.length - 1; k > 0; k--) {
    const ta = points[k - 1].time.getTime();
    const tb = points[k].time.getTime();
    if (Math.min(ta, tb) <= t && t <= Math.max(ta, tb)) {
      if (ta === tb) return points[k].value;
      return points[k - 1].value + ((points[k].value - points[k - 1].value) * (t - ta)) / (tb - ta);
    }
  }
  let nearest = points[0];
  for (const point of points) {
    if (Math.abs(point.time.getTime() - t) < Math.abs(nearest.time.getTime() - t)) nearest = point;
  }
  return nearest.value;
}

/**
 * A scale to propose for drawing: twice the top of the chart's y-axis, rounded up to one significant digit.
 *
 * @param {number|null} yAxisMax - The top of the y-axis as shown.
 * @returns {number} The scale, at least 1.
 */
export function proposedDrawScale(yAxisMax) {
  const target = 2 * (yAxisMax > 0 && isFinite(yAxisMax) ? yAxisMax : 0.5);
  const magnitude = Math.pow(10, Math.floor(Math.log10(target)));
  return Math.max(1, Math.ceil(target / magnitude) * magnitude);
}

/**
 * Remove the draft values within a time range, such as one group of groupDrafts.
 *
 * @param {Object[]} drafts - The current draft values.
 * @param {number} startMs - The start of the range, in milliseconds since the epoch.
 * @param {number} endMs - The end of the range, in milliseconds since the epoch.
 * @returns {Object[]} The remaining draft values.
 */
export function removeDraftsIn(drafts, startMs, endMs) {
  return drafts.filter((draft) => draft.start.getTime() < startMs || draft.start.getTime() >= endMs);
}

/**
 * Group draft values into runs of adjacent slots with the same value, to list them compactly.
 *
 * @param {Object[]} drafts - The draft values, sorted by start.
 * @returns {{start: Date, end: Date, value: number, count: number}[]} The groups, sorted by start.
 */
export function groupDrafts(drafts) {
  const groups = [];
  for (const draft of drafts) {
    const last = groups[groups.length - 1];
    if (last && last.value === draft.value && last.end.getTime() === draft.start.getTime()) {
      last.end = new Date(draft.end);
      last.count++;
    } else {
      groups.push({ start: new Date(draft.start), end: new Date(draft.end), value: draft.value, count: 1 });
    }
  }
  return groups;
}

/**
 * Read a typed value, or null when it is not a number.
 *
 * Typing is the only way to give a value for now.
 * Another source (e.g. where the user clicks on the y-axis) would hand its number to fillSlots in the same way.
 *
 * @param {string} text - The text typed into the value field.
 * @returns {number|null} The value.
 */
export function parseDraftValue(text) {
  const trimmed = String(text == null ? "" : text).trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return isFinite(value) ? value : null;
}

const ISO_DURATION = /^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)W)?(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$/;

/**
 * Read an ISO 8601 duration as the sensor data API does, or null when it is not one the API accepts.
 *
 * Weeks, days, hours, minutes and seconds make a fixed span of time, so P1D is 24 hours, even on a day with a DST transition.
 * Only years and months have no fixed length; they are kept apart, to be counted on the calendar (see rangeFromStartAndDuration).
 * Like the API, only whole minutes are accepted.
 *
 * @param {string} text - The duration, e.g. "PT2H" or "P1D".
 * @returns {{months: number, ms: number}|null} The calendar months and the fixed span, in milliseconds.
 */
export function parseIsoDuration(text) {
  const trimmed = String(text == null ? "" : text).trim().toUpperCase();
  const match = ISO_DURATION.exec(trimmed);
  if (!match || trimmed === "P" || trimmed.endsWith("T")) return null;
  const n = (i) => (match[i] ? Number(match[i]) : 0);
  const ms = (((n(3) * 7 + n(4)) * 24 + n(5)) * 60 + n(6)) * 60000 + n(7) * 1000;
  if (Math.abs(ms % 60000) > 1e-6) return null;
  return { months: n(1) * 12 + n(2), ms: Math.round(ms) };
}

/**
 * Write a span of time as an ISO 8601 duration, in days, hours and minutes.
 *
 * Days are fixed spans of 24 hours here, as in the API, so 25 hours is P1DT1H.
 *
 * @param {number} ms - The span, in milliseconds.
 * @returns {string} The duration, e.g. "PT2H".
 */
export function formatIsoDuration(ms) {
  const minutes = Math.round(ms / 60000);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const rest = minutes % 60;
  const time = (hours ? hours + "H" : "") + (rest ? rest + "M" : "");
  if (!days && !time) return "PT0M";
  return "P" + (days ? days + "D" : "") + (time ? "T" + time : "");
}

/**
 * The time range a start and a duration describe, as the sensor data API reads them.
 *
 * The fixed span is added as is; calendar months are added at the start's UTC offset,
 * as the API does with a timezone-aware start.
 *
 * @param {Date} start - The start.
 * @param {{months: number, ms: number}} duration - A duration from parseIsoDuration.
 * @returns {{start: Date, end: Date}} The range.
 */
export function rangeFromStartAndDuration(start, duration) {
  let end = new Date(start);
  if (duration.months) {
    const offsetMs = -start.getTimezoneOffset() * 60000;
    const wallClock = new Date(start.getTime() + offsetMs);
    wallClock.setUTCMonth(wallClock.getUTCMonth() + duration.months);
    end = new Date(wallClock.getTime() - offsetMs);
  }
  return { start: new Date(start), end: new Date(end.getTime() + duration.ms) };
}

/**
 * A time as the value of a datetime-local field, in local time, to the minute.
 *
 * @param {Date} date - The time.
 * @returns {string} The field value, e.g. "2026-10-25T01:00".
 */
export function toDatetimeLocalValue(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/**
 * Why draft values cannot be created for this sensor here, or null when they can.
 *
 * @param {number} resolutionMs - The sensor's event resolution, in milliseconds.
 * @param {boolean} isTouch - Whether the primary pointer is a touch screen.
 * @returns {string|null} The reason, to show in the panel.
 */
export function draftValuesUnavailableReason(resolutionMs, isTouch) {
  if (isTouch) return "Draft values are created with the select tool on the chart, which needs a mouse.";
  if (!(resolutionMs > 0)) return "This sensor records instants rather than events, so there are no slots to fill.";
  return null;
}

// With the UTC offset, so that the two occurrences of an hour repeated at a DST transition can be told apart.
function defaultFormatTime(date) {
  return date.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short",
  });
}

/**
 * Wire the "Draft values" side panel.
 *
 * The panel's elements are found by their data attributes inside the root:
 * data-draft-draw (the Draw on chart toggle, with data-draft-draw-text for its label, data-draft-drawing explaining it
 * and holding data-draft-draw-max, the scale to draw on, and data-draft-typed, the fields hidden while drawing; all optional),
 * data-draft-record (the Select on chart toggle, with data-draft-record-text for its label),
 * data-draft-start and data-draft-duration (a datetime-local and a text field), data-draft-value (the value field), data-draft-add,
 * data-draft-selection (describes the selection), data-draft-list (one row per group of draft values), data-draft-count,
 * data-draft-empty, data-draft-cancel (Discard), and data-draft-unavailable (a note shown instead of the controls).
 *
 * While recording, a "chartrangeselected" event on the target selects the slots its range covers,
 * and so does a start and an ISO 8601 duration typed in, as the sensor data API takes them, which start recording if need be.
 * Each fills in the other: a selection on the chart shows as a start and a duration, and a typed one shows on the chart.
 * While drawing, a "chartdrawn" event on the target turns the stroke it carries into draft values (see strokeToDrafts).
 *
 * @param {HTMLElement} root - The panel.
 * @param {Object} options
 * @param {number} options.sensorId - The sensor, passed on with the draft values.
 * @param {number} options.resolutionMs - The sensor's event resolution, in milliseconds.
 * @param {string} [options.unit] - The sensor's unit, shown with each value.
 * @param {string} [options.timeZone] - The sensor's timezone, to show a group of draft values that ends on the day it starts without repeating that day.
 * @param {function(): number} options.getAnchorMs - Any event start of the sensor, in milliseconds since the epoch.
 * @param {Object} options.chart - How the panel drives the chart:
 *   startSelecting() turns on the select tool (it may return a promise, and false when that is not possible),
 *   stopSelecting(), startDrawing() and stopDrawing() likewise for the draw tool, showSelection(range|null) and showDrafts(drafts).
 * @param {function(string): boolean} [options.confirm] - Asks the user to confirm (window.confirm by default).
 * @param {EventTarget} [options.target] - Where chart events arrive and the hand-off is dispatched (document by default).
 * @param {Window} [options.win] - Where leaving the page is guarded (window by default).
 * @param {boolean} [options.isTouch] - Whether the primary pointer is a touch screen.
 * @param {function(Date): string} [options.formatTime] - How times are shown in the panel.
 * @returns {Object} The panel's controller.
 */
export function wireDraftValuesPanel(root, options) {
  const opts = Object.assign(
    {
      unit: "",
      confirm: (message) => window.confirm(message),
      target: document,
      win: window,
      isTouch: false,
      formatTime: defaultFormatTime,
    },
    options,
  );
  const el = (name) => root.querySelector("[data-draft-" + name + "]");
  const recordButton = el("record");
  const valueInput = el("value");
  const recordText = el("record-text") || recordButton;
  const drawButton = el("draw");
  const drawText = el("draw-text") || drawButton;
  const drawingNote = el("drawing");
  const drawMaxInput = el("draw-max");
  const typedFields = el("typed");
  const startInput = el("start");
  const durationInput = el("duration");
  const addButton = el("add");
  const selectionInfo = el("selection");
  const list = el("list");
  const emptyNote = el("empty");
  const cancelButton = el("cancel");
  const countBadge = el("count");
  const unavailableNote = el("unavailable");
  const controls = el("controls");

  let drafts = [];
  let recording = false;
  let drawing = false;
  let slots = [];

  const unavailable = draftValuesUnavailableReason(opts.resolutionMs, opts.isTouch);
  if (unavailable) {
    unavailableNote.textContent = unavailable;
    unavailableNote.classList.remove("d-none");
    controls.classList.add("d-none");
  }

  const withUnit = (value) => (opts.unit ? value + " " + opts.unit : String(value));

  function render() {
    recordText.textContent = recording ? "Stop selecting" : "Select on chart";
    recordButton.setAttribute("aria-pressed", recording ? "true" : "false");
    if (drawButton) {
      drawText.textContent = drawing ? "Stop drawing" : "Draw on chart";
      drawButton.setAttribute("aria-pressed", drawing ? "true" : "false");
      drawingNote.classList.toggle("d-none", !drawing);
      // A typed range and value do not apply while drawing.
      if (typedFields) typedFields.classList.toggle("d-none", drawing);
    }
    addButton.disabled = !pending();
    // Green as soon as a value is typed, so the step that is easy to miss stands out, and once values were added, to show they were.
    const green = parseDraftValue(valueInput.value) !== null || drafts.length > 0;
    addButton.classList.toggle("btn-success", green);
    addButton.classList.toggle("btn-light", !green);
    // A disabled button is faded, which would hide the green.
    addButton.style.opacity = green ? "1" : "";
    cancelButton.classList.toggle("d-none", drafts.length === 0);
    if (!recording) {
      selectionInfo.textContent = "";
    } else if (slots.length === 0) {
      selectionInfo.textContent = "Drag across the chart, click an event, or enter a start and duration.";
    } else {
      const count = slots.length === 1 ? "1 slot" : slots.length + " slots";
      selectionInfo.textContent =
        "Selected: " + opts.formatTime(slots[0].start) + " until " + opts.formatTime(slots[slots.length - 1].end) + " (" + count + ").";
    }
    // One row per run of the same value, rather than one per event, which could be hundreds.
    list.replaceChildren(
      ...groupDrafts(drafts).map((group) => {
        const row = document.createElement("li");
        row.className = "list-group-item d-flex justify-content-between align-items-center py-1 small";
        row.dataset.draftStart = String(group.start.getTime());
        const text = document.createElement("span");
        const when = document.createElement("div");
        when.textContent = opts.formatTime(group.start) + " – " + formatGroupEnd(group);
        const what = document.createElement("div");
        what.className = "fw-bold";
        what.textContent = withUnit(group.value) + " · " + (group.count === 1 ? "1 value" : group.count + " values");
        text.append(when, what);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "btn-close ms-2";
        remove.title = "Remove these draft values";
        remove.setAttribute("aria-label", "Remove the draft values from " + opts.formatTime(group.start));
        remove.addEventListener("click", () => controller.removeRange(group.start.getTime(), group.end.getTime()));
        row.append(text, remove);
        return row;
      }),
    );
    emptyNote.classList.toggle("d-none", drafts.length > 0);
    countBadge.textContent = String(drafts.length);
    countBadge.classList.toggle("d-none", drafts.length === 0);
  }

  // The end of a group of draft values, without repeating its date when it ends on the day it starts.
  function formatGroupEnd(group) {
    if (!opts.timeZone) return opts.formatTime(group.end);
    const day = (date) => date.toLocaleDateString("en-CA", { timeZone: opts.timeZone });
    // A group ending at midnight ends on the day it covers.
    const lastMoment = new Date(group.end.getTime() - 1);
    if (day(group.start) !== day(lastMoment)) return opts.formatTime(group.end);
    return group.end.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", timeZone: opts.timeZone });
  }

  // Whether a selection and a value wait to be added.
  function pending() {
    return recording && slots.length > 0 && parseDraftValue(valueInput.value) !== null;
  }

  function setDrafts(next) {
    drafts = next;
    opts.chart.showDrafts(drafts.slice());
  }

  function clearSelection() {
    slots = [];
    opts.chart.showSelection(null);
    startInput.value = "";
    durationInput.value = "";
    durationInput.classList.remove("is-invalid");
  }

  const controller = {
    get drafts() {
      return drafts.slice();
    },
    get recording() {
      return recording;
    },
    get drawing() {
      return drawing;
    },
    // Turn on the draw tool, so that a stroke on the chart makes draft values, ending selecting.
    async draw() {
      if (drawing || unavailable) return;
      controller.endRecording();
      const started = await opts.chart.startDrawing();
      if (started === false) return;
      drawing = true;
      // Propose room above what the chart shows, as the values to draw may lie above the data so far.
      if (drawMaxInput && opts.chart.getYAxisMax) {
        if (!drawMaxInput.value) drawMaxInput.value = String(proposedDrawScale(opts.chart.getYAxisMax()));
        controller.setDrawScale(drawMaxInput.value);
      }
      render();
    },
    // Let the chart reach up to this value while drawing.
    setDrawScale(text) {
      const yMax = parseDraftValue(text);
      if (!drawing || yMax === null || !opts.chart.setDrawScale) return;
      opts.chart.setDrawScale(yMax);
    },
    stopDrawing() {
      if (!drawing) return;
      drawing = false;
      opts.chart.stopDrawing();
      render();
    },
    // Turn a stroke drawn on the chart into draft values, replacing what it overlaps.
    addStroke(stroke) {
      if (!drawing || !stroke) return;
      const drawn = strokeToDrafts(stroke.points, opts.resolutionMs, opts.getAnchorMs(), stroke.step);
      if (drawn.length > MAX_DRAFT_SLOTS) {
        showToastIfAvailable("That line crosses " + drawn.length + " slots; please draw at most " + MAX_DRAFT_SLOTS + " at once.", "error");
        return;
      }
      setDrafts(mergeDrafts(drafts, drawn));
      render();
    },
    get slots() {
      return slots.slice();
    },
    // Turn on the select tool, so that selections on the chart pick slots.
    async record() {
      if (recording || unavailable) return;
      controller.stopDrawing();
      const started = await opts.chart.startSelecting();
      if (started === false) return;
      recording = true;
      render();
    },
    // End recording (Stop), keeping the draft values without handing them over; also when the chart can no longer select.
    endRecording() {
      if (!recording) return;
      recording = false;
      clearSelection();
      opts.chart.stopSelecting();
      render();
    },
    // End recording, keep the draft values, and hand them over, to be saved as they are ("save") or previewed first ("preview").
    // A selection with a value that was not added yet is added first, so it is not lost.
    handOver(action) {
      controller.add();
      if (drafts.length === 0) return;
      controller.endRecording();
      controller.stopDrawing();
      opts.target.dispatchEvent(
        new CustomEvent(DRAFT_VALUES_RECORDED_EVENT, {
          detail: { sensorId: opts.sensorId, drafts: drafts.map((d) => ({ ...d })), action: action },
        }),
      );
    },
    // Select the slots a range on the chart covers (null clears the selection).
    select(range) {
      if (!recording) return;
      if (!range) {
        clearSelection();
        render();
        return;
      }
      const selected = selectionToSlots(range, opts.resolutionMs, opts.getAnchorMs());
      if (selected.length > MAX_DRAFT_SLOTS) {
        showToastIfAvailable(
          "That selection holds " + selected.length + " slots; please select at most " + MAX_DRAFT_SLOTS + " at once.",
          "error",
        );
        clearSelection();
      } else {
        slots = selected;
        const covered = slots.length > 0 ? { start: slots[0].start, end: slots[slots.length - 1].end } : null;
        opts.chart.showSelection(covered);
        if (covered) {
          startInput.value = toDatetimeLocalValue(covered.start);
          durationInput.value = formatIsoDuration(covered.end - covered.start);
          durationInput.classList.remove("is-invalid");
        }
      }
      render();
    },
    // Select the slots that the typed start and duration cover, once both are filled in, starting to record if need be.
    async selectTyped() {
      const start = new Date(startInput.value);
      const duration = parseIsoDuration(durationInput.value);
      durationInput.classList.toggle("is-invalid", durationInput.value.trim() !== "" && duration === null);
      if (!isFinite(start.getTime()) || duration === null) return;
      // Starting to record must not lose what was typed, so it is read before.
      const range = rangeFromStartAndDuration(start, duration);
      await controller.record();
      controller.select(range);
    },
    // Give the selected slots the typed value, then clear the selection (the value stays, to be used again).
    add() {
      const value = parseDraftValue(valueInput.value);
      if (!recording || slots.length === 0 || value === null) return;
      setDrafts(fillSlots(drafts, slots, value));
      clearSelection();
      render();
    },
    remove(startMs) {
      setDrafts(removeDraft(drafts, startMs));
      render();
    },
    removeRange(startMs, endMs) {
      setDrafts(removeDraftsIn(drafts, startMs, endMs));
      render();
    },
    // Discard all draft values, after confirmation, and end recording.
    cancel() {
      if (drafts.length > 0 && !opts.confirm("Discard all " + drafts.length + " draft values? They have not been saved.")) {
        return;
      }
      controller.discard();
    },
    // Discard all draft values without asking, and end recording, e.g. once they are saved, or after the preview asked.
    discard() {
      controller.endRecording();
      controller.stopDrawing();
      setDrafts([]);
      render();
    },
  };

  // The toggle and Discard are links, like the secondary actions of the other panels.
  recordButton.addEventListener("click", (event) => {
    event.preventDefault();
    recording ? controller.endRecording() : controller.record();
  });
  addButton.addEventListener("click", () => controller.add());
  cancelButton.addEventListener("click", (event) => {
    event.preventDefault();
    controller.cancel();
  });
  valueInput.addEventListener("input", render);
  startInput.addEventListener("change", () => controller.selectTyped());
  durationInput.addEventListener("change", () => controller.selectTyped());
  valueInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      controller.add();
    }
  });
  opts.target.addEventListener("chartrangeselected", (event) => controller.select(event.detail));
  if (drawButton) {
    drawButton.addEventListener("click", (event) => {
      event.preventDefault();
      drawing ? controller.stopDrawing() : controller.draw();
    });
  }
  opts.target.addEventListener("chartdrawn", (event) => controller.addStroke(event.detail));
  if (drawMaxInput) drawMaxInput.addEventListener("change", () => controller.setDrawScale(drawMaxInput.value));
  // Another chart tool was picked, which ended drawing.
  opts.target.addEventListener("chartdrawmodeended", () => {
    drawing = false;
    render();
  });
  // Draft values only live in this page, so leaving it would lose them.
  opts.win.addEventListener("beforeunload", (event) => {
    if (drafts.length === 0) return;
    event.preventDefault();
    event.returnValue = "";
  });

  render();
  return controller;
}

function showToastIfAvailable(message, type) {
  if (typeof showToast === "function") showToast(message, type);
}
