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
 * data-draft-record (the Record/Stop button), data-draft-value (the value field), data-draft-add,
 * data-draft-selection (describes the selection), data-draft-list, data-draft-empty, data-draft-cancel
 * and data-draft-unavailable (a note shown instead of the controls).
 *
 * While recording, a "chartrangeselected" event on the target selects the slots its range covers.
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
    cancelButton.disabled = !recording && drafts.length === 0;
    if (!recording) {
      selectionInfo.textContent = "Press Record, then select a time range on the chart, or click a slot.";
    } else if (slots.length === 0) {
      selectionInfo.textContent = "Select a time range on the chart, or click a slot.";
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
        opts.chart.showSelection(slots.length > 0 ? { start: slots[0].start, end: slots[slots.length - 1].end } : null);
      }
      render();
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
