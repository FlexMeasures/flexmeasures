/**
 * Draft sensor values, created on the sensor graph before anything is saved (#2468).
 *
 * A draft value covers one event (slot) of a sensor: { start: Date, end: Date, value: number }.
 * Lists of draft values are kept sorted by start, and are never changed in place.
 *
 * The pure functions turn a selection on the chart into slots, and fill, replace and remove draft values.
 * wireDraftValuesPanel connects them to the "Draft values" side panel on the sensor page.
 * Nothing here writes to the database: Stop hands the draft values over in a DRAFT_VALUES_RECORDED_EVENT,
 * for the preview (#2469) to pick up.
 */

import { snapRangeToEvents } from "./chart-data-utils.js";

const DAY_MS = 24 * 60 * 60 * 1000;

// More slots than this in one selection would make the panel's list unwieldy, so such a selection is refused.
export const MAX_DRAFT_SLOTS = 2000;

// Fired on the panel's event target when the user stops recording, with { sensorId, drafts } as detail.
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
  const added = slots.map((slot) => ({ start: new Date(slot.start), end: new Date(slot.end), value: value }));
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
 * data-draft-record (the Record/Stop button), data-draft-start and data-draft-duration (a datetime-local and a text field),
 * data-draft-value (the value field), data-draft-add, data-draft-selection (describes the selection),
 * data-draft-list, data-draft-empty, data-draft-cancel and data-draft-unavailable (a note shown instead of the controls).
 *
 * While recording, a "chartrangeselected" event on the target selects the slots its range covers,
 * and so does a start and an ISO 8601 duration typed in, as the sensor data API takes them.
 * Each fills in the other: a selection on the chart shows as a start and a duration, and a typed one shows on the chart.
 *
 * @param {HTMLElement} root - The panel.
 * @param {Object} options
 * @param {number} options.sensorId - The sensor, passed on with the draft values.
 * @param {number} options.resolutionMs - The sensor's event resolution, in milliseconds.
 * @param {string} [options.unit] - The sensor's unit, shown with each value.
 * @param {function(): number} options.getAnchorMs - Any event start of the sensor, in milliseconds since the epoch.
 * @param {Object} options.chart - How the panel drives the chart:
 *   startSelecting() turns on the select tool (it may return a promise, and false when that is not possible),
 *   stopSelecting(), showSelection(range|null) and showDrafts(drafts).
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
  const startInput = el("start");
  const durationInput = el("duration");
  const addButton = el("add");
  const selectionInfo = el("selection");
  const list = el("list");
  const emptyNote = el("empty");
  const cancelButton = el("cancel");
  const unavailableNote = el("unavailable");
  const controls = el("controls");

  let drafts = [];
  let recording = false;
  let slots = [];

  const unavailable = draftValuesUnavailableReason(opts.resolutionMs, opts.isTouch);
  if (unavailable) {
    unavailableNote.textContent = unavailable;
    unavailableNote.classList.remove("d-none");
    controls.classList.add("d-none");
  }

  const withUnit = (value) => (opts.unit ? value + " " + opts.unit : String(value));

  function render() {
    recordButton.textContent = recording ? "Stop" : "Record";
    recordButton.setAttribute("aria-pressed", recording ? "true" : "false");
    recordButton.classList.toggle("btn-danger", recording);
    recordButton.classList.toggle("btn-success", !recording);
    addButton.disabled = !recording || slots.length === 0 || parseDraftValue(valueInput.value) === null;
    startInput.disabled = durationInput.disabled = !recording;
    cancelButton.disabled = !recording && drafts.length === 0;
    if (!recording) {
      selectionInfo.textContent = "Press Record, then select a time range on the chart, click a slot, or enter a start and duration.";
    } else if (slots.length === 0) {
      selectionInfo.textContent = "Select a time range on the chart, click a slot, or enter a start and duration.";
    } else {
      const count = slots.length === 1 ? "1 slot" : slots.length + " slots";
      selectionInfo.textContent =
        "Selected: " + opts.formatTime(slots[0].start) + " until " + opts.formatTime(slots[slots.length - 1].end) + " (" + count + ").";
    }
    list.replaceChildren(
      ...drafts.map((draft) => {
        const row = document.createElement("li");
        row.className = "list-group-item d-flex justify-content-between align-items-center py-1 small";
        row.dataset.draftStart = String(draft.start.getTime());
        const text = document.createElement("span");
        text.textContent = opts.formatTime(draft.start) + ": " + withUnit(draft.value);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "btn-close ms-2";
        remove.title = "Remove this draft value";
        remove.setAttribute("aria-label", "Remove the draft value at " + opts.formatTime(draft.start));
        remove.addEventListener("click", () => controller.remove(draft.start.getTime()));
        row.append(text, remove);
        return row;
      }),
    );
    emptyNote.classList.toggle("d-none", drafts.length > 0);
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
    get slots() {
      return slots.slice();
    },
    // Turn on the select tool, so that selections on the chart pick slots.
    async record() {
      if (recording || unavailable) return;
      const started = await opts.chart.startSelecting();
      if (started === false) return;
      recording = true;
      render();
    },
    // End recording without handing the draft values over, e.g. when the chart can no longer select.
    endRecording() {
      if (!recording) return;
      recording = false;
      clearSelection();
      opts.chart.stopSelecting();
      render();
    },
    // End recording, keep the draft values, and hand them over for the preview (#2469).
    stop() {
      if (!recording) return;
      controller.endRecording();
      opts.target.dispatchEvent(
        new CustomEvent(DRAFT_VALUES_RECORDED_EVENT, {
          detail: { sensorId: opts.sensorId, drafts: drafts.map((d) => ({ ...d })) },
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
    // Select the slots that the typed start and duration cover, once both are filled in.
    selectTyped() {
      if (!recording) return;
      const start = new Date(startInput.value);
      const duration = parseIsoDuration(durationInput.value);
      durationInput.classList.toggle("is-invalid", durationInput.value.trim() !== "" && duration === null);
      if (!isFinite(start.getTime()) || duration === null) return;
      controller.select(rangeFromStartAndDuration(start, duration));
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
    // Discard all draft values, after confirmation, and end recording.
    cancel() {
      if (drafts.length > 0 && !opts.confirm("Discard all " + drafts.length + " draft values? They have not been saved.")) {
        return;
      }
      controller.endRecording();
      setDrafts([]);
      render();
    },
  };

  recordButton.addEventListener("click", () => (recording ? controller.stop() : controller.record()));
  addButton.addEventListener("click", () => controller.add());
  cancelButton.addEventListener("click", () => controller.cancel());
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
