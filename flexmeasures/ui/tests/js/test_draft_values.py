"""Tests for flexmeasures/ui/static/js/draft-values.js."""

# A panel with every element wireDraftValuesPanel looks for, and a chart that records what the panel asks of it.
PANEL = """
import { wireDraftValuesPanel, DRAFT_VALUES_RECORDED_EVENT } from "/js/draft-values.js";
document.body.insertAdjacentHTML("beforeend", `
  <div id="panel">
    <div data-draft-unavailable class="d-none"></div>
    <div data-draft-controls>
      <button data-draft-record type="button">Record</button>
      <input data-draft-value type="number" />
      <button data-draft-add type="button">Add</button>
      <div data-draft-selection></div>
      <ul data-draft-list></ul>
      <div data-draft-empty>No draft values yet.</div>
      <button data-draft-cancel type="button">Cancel</button>
    </div>
  </div>`);
const root = document.getElementById("panel");
const button = (name) => root.querySelector("[data-draft-" + name + "]");
const chart = { selecting: false, selection: null, drafts: [] };
chart.startSelecting = () => { chart.selecting = true; };
chart.stopSelecting = () => { chart.selecting = false; };
chart.showSelection = (range) => { chart.selection = range; };
chart.showDrafts = (drafts) => { chart.drafts = drafts; };
const confirmations = [];
let confirmAnswer = true;
const target = new EventTarget();
const win = new EventTarget();
const handedOver = [];
target.addEventListener(DRAFT_VALUES_RECORDED_EVENT, (event) => handedOver.push(event.detail));
const QUARTER = 15 * 60 * 1000;
const T0 = Date.UTC(2026, 0, 1, 0, 0);
const panel = wireDraftValuesPanel(root, {
  sensorId: 42, resolutionMs: QUARTER, unit: "kWh", getAnchorMs: () => T0,
  chart: chart, target: target, win: win,
  confirm: (message) => { confirmations.push(message); return confirmAnswer; },
  formatTime: (date) => date.toISOString(),
});
const selectOnChart = (start, end) =>
  target.dispatchEvent(new CustomEvent("chartrangeselected", { detail: { start: new Date(start), end: new Date(end) } }));
const typeValue = (text) => {
  button("value").value = text;
  button("value").dispatchEvent(new Event("input"));
};
"""


def test_a_selection_becomes_whole_slots(assert_js):
    """A drag is widened to the events it touches, one slot per event."""
    assert_js("""
        import { selectionToSlots } from "/js/draft-values.js";
        const QUARTER = 15 * 60 * 1000;
        const t0 = Date.UTC(2026, 0, 1, 10, 0);
        const slots = selectionToSlots({ start: new Date(t0 + 5 * 60000), end: new Date(t0 + 2 * 3600000 - 5 * 60000) }, QUARTER, t0);
        eq("a two-hour drag over 15-minute events gives eight slots", slots.length, 8);
        eq("the first slot starts at the event the drag starts in", slots[0].start.getTime(), t0);
        eq("the last slot ends at the end of the event the drag ends in", slots[7].end.getTime(), t0 + 2 * 3600000);
        check("the slots are contiguous", slots.every((s, i) => i === 0 || s.start.getTime() === slots[i - 1].end.getTime()), "");
        check("every slot is one event long", slots.every((s) => s.end - s.start === QUARTER), "");
        """)


def test_a_click_selects_the_slot_it_is_in(assert_js):
    assert_js("""
        import { selectionToSlots } from "/js/draft-values.js";
        const HOUR = 3600 * 1000;
        const t0 = Date.UTC(2026, 0, 1, 0, 0);
        const click = new Date(t0 + 5 * HOUR + 20 * 60000);
        const slots = selectionToSlots({ start: click, end: click }, HOUR, t0);
        eq("a click gives one slot", slots.length, 1);
        eq("which is the event the click lies in", slots[0].start.getTime(), t0 + 5 * HOUR);
        eq("and lasts one event", slots[0].end.getTime(), t0 + 6 * HOUR);
        """)


def test_no_slots_without_a_resolution_or_a_selection(assert_js):
    assert_js("""
        import { selectionToSlots } from "/js/draft-values.js";
        const now = new Date();
        eq("an instantaneous sensor has no slots", selectionToSlots({ start: now, end: new Date(+now + 3600000) }, 0, +now).length, 0);
        eq("no selection gives no slots", selectionToSlots(null, 900000, +now).length, 0);
        """)


def test_slots_across_dst_transitions(assert_js):
    """Sub-daily slots stay one resolution long through a transition, and daily slots follow the local calendar."""
    assert_js(
        """
        import { selectionToSlots } from "/js/draft-values.js";
        const QUARTER = 15 * 60 * 1000;
        // Amsterdam springs forward on 29 March 2026, from 02:00 to 03:00 local time.
        const springStart = new Date(2026, 2, 29, 0, 0);
        const springEnd = new Date(2026, 2, 29, 5, 0);
        const spring = selectionToSlots({ start: springStart, end: springEnd }, QUARTER, springStart.getTime());
        eq("five local hours over the spring transition are four real hours of quarters", spring.length, 16);
        check("every quarter is 15 minutes long", spring.every((s) => s.end - s.start === QUARTER), "");
        eq("no slot starts in the skipped hour", spring.filter((s) => s.start.getHours() === 2).length, 0);

        // And falls back on 25 October 2026, from 03:00 to 02:00 local time.
        const autumnStart = new Date(2026, 9, 25, 0, 0);
        const autumnEnd = new Date(2026, 9, 25, 5, 0);
        const autumn = selectionToSlots({ start: autumnStart, end: autumnEnd }, QUARTER, autumnStart.getTime());
        eq("five local hours over the autumn transition are six real hours of quarters", autumn.length, 24);
        eq("the repeated hour has eight quarters", autumn.filter((s) => s.start.getHours() === 2).length, 8);

        const DAY = 24 * 3600 * 1000;
        const midnight = new Date(2026, 9, 24, 0, 0);
        const days = selectionToSlots({ start: new Date(2026, 9, 24, 12, 0), end: new Date(2026, 9, 26, 12, 0) }, DAY, midnight.getTime());
        eq("three local days are touched", days.length, 3);
        check("every day starts at local midnight", days.every((s) => s.start.getHours() === 0 && s.start.getMinutes() === 0),
              days.map((s) => s.start.toString()).join(" | "));
        eq("the day of the transition lasts 25 hours", days[1].end - days[1].start, 25 * 3600 * 1000);
        """,
        timezone="Europe/Amsterdam",
    )


def test_filling_replaces_what_it_overlaps(assert_js):
    assert_js("""
        import { fillSlots, removeDraft } from "/js/draft-values.js";
        const HOUR = 3600 * 1000;
        const t0 = Date.UTC(2026, 0, 1, 0, 0);
        const slot = (h) => ({ start: new Date(t0 + h * HOUR), end: new Date(t0 + (h + 1) * HOUR) });
        let drafts = fillSlots([], [slot(2), slot(3)], 5);
        eq("filling two slots gives two draft values", drafts.map((d) => d.value), [5, 5]);
        drafts = fillSlots(drafts, [slot(0)], 1);
        eq("draft values stay sorted by start", drafts.map((d) => d.start.getTime()), [t0, t0 + 2 * HOUR, t0 + 3 * HOUR]);
        drafts = fillSlots(drafts, [slot(3), slot(4)], 7);
        eq("adding over a draft slot replaces it", drafts.map((d) => d.value), [1, 5, 7, 7]);
        const shifted = { start: new Date(t0 + 1.5 * HOUR), end: new Date(t0 + 2.5 * HOUR) };
        drafts = fillSlots(drafts, [shifted], 9);
        eq("a slot on a shifted grid replaces the draft value it overlaps", drafts.map((d) => d.value), [1, 9, 7, 7]);
        const before = drafts.slice();
        drafts = removeDraft(drafts, t0);
        eq("removing a draft value leaves the others", drafts.map((d) => d.value), [9, 7, 7]);
        eq("the original list is left unchanged", before.length, 4);
        """)


def test_typed_values(assert_js):
    assert_js("""
        import { parseDraftValue } from "/js/draft-values.js";
        eq("a number is read", parseDraftValue(" 4.5 "), 4.5);
        eq("zero is a value", parseDraftValue("0"), 0);
        eq("a negative number is read", parseDraftValue("-2"), -2);
        eq("nothing typed is no value", parseDraftValue(""), null);
        eq("text is no value", parseDraftValue("abc"), null);
        eq("infinity is no value", parseDraftValue("Infinity"), null);
        """)


def test_the_panel_explains_when_drafts_are_unavailable(assert_js):
    assert_js("""
        import { draftValuesUnavailableReason } from "/js/draft-values.js";
        check("touch devices are told why", /mouse/.test(draftValuesUnavailableReason(900000, true)), "");
        check("instantaneous sensors are told why", /instants/.test(draftValuesUnavailableReason(0, false)), "");
        eq("a mouse and a resolution make drafts available", draftValuesUnavailableReason(900000, false), null);
        """)


def test_record_select_add_and_stop(assert_js):
    """Record turns on the select tool, a selection plus a value adds draft values, and Stop hands them over."""
    assert_js(PANEL + """
        eq("the panel starts idle", button("record").textContent, "Record");
        selectOnChart(T0, T0 + 3600000);
        eq("a selection is ignored until recording", panel.slots.length, 0);

        button("record").click();
        await Promise.resolve();
        check("Record turns on the select tool", chart.selecting, "");
        eq("Stop replaces Record while recording", button("record").textContent, "Stop");

        selectOnChart(T0 + 60000, T0 + 3600000 - 60000);
        eq("a selection picks the slots it touches", panel.slots.length, 4);
        eq("the chart shows the snapped selection", chart.selection.end.getTime(), T0 + 3600000);
        check("Add waits for a value", button("add").disabled, "");
        typeValue("3.5");
        check("Add is offered with a selection and a value", !button("add").disabled, "");
        button("add").click();
        eq("every slot got the value", panel.drafts.map((d) => d.value), [3.5, 3.5, 3.5, 3.5]);
        eq("the chart shows the draft values", chart.drafts.length, 4);
        eq("the panel lists them", button("list").children.length, 4);
        check("each row has the value and its unit", button("list").children[0].textContent.includes("3.5 kWh"), button("list").children[0].textContent);
        eq("the selection is cleared", chart.selection, null);
        eq("the value stays for the next selection", button("value").value, "3.5");

        button("list").children[1].querySelector("button").click();
        eq("a row's remove button removes that draft value", panel.drafts.length, 3);

        button("record").click();
        check("Stop turns off the select tool", !chart.selecting, "");
        eq("Record is offered again", button("record").textContent, "Record");
        eq("the draft values are kept", panel.drafts.length, 3);
        eq("they are handed over once", handedOver.length, 1);
        eq("for this sensor", handedOver[0].sensorId, 42);
        eq("with every draft value", handedOver[0].drafts.length, 3);
        """)


def test_cancel_asks_before_discarding(assert_js):
    assert_js(PANEL + """
        await panel.record();
        selectOnChart(T0, T0);
        typeValue("1");
        panel.add();
        confirmAnswer = false;
        button("cancel").click();
        eq("cancel asks first", confirmations.length, 1);
        eq("declining keeps the draft values", panel.drafts.length, 1);
        check("and keeps recording", panel.recording, "");
        confirmAnswer = true;
        button("cancel").click();
        eq("confirming discards them", panel.drafts.length, 0);
        eq("from the chart, too", chart.drafts.length, 0);
        check("and ends recording", !panel.recording && !chart.selecting, "");
        eq("nothing is handed over", handedOver.length, 0);
        """)


def test_leaving_the_page_with_drafts_asks_for_confirmation(assert_js):
    assert_js(PANEL + """
        const leave = () => {
            const event = new Event("beforeunload", { cancelable: true });
            win.dispatchEvent(event);
            return event.defaultPrevented;
        };
        check("leaving without draft values is not held up", !leave(), "");
        await panel.record();
        selectOnChart(T0, T0);
        typeValue("1");
        panel.add();
        check("leaving with draft values asks first", leave(), "");
        panel.stop();
        check("so it does after Stop, since nothing was saved", leave(), "");
        """)


def test_a_selection_too_large_is_refused(assert_js):
    assert_js(PANEL + """
        import { MAX_DRAFT_SLOTS } from "/js/draft-values.js";
        const toasts = [];
        window.showToast = (message, type) => toasts.push({ message, type });
        await panel.record();
        selectOnChart(T0, T0 + (MAX_DRAFT_SLOTS + 1) * QUARTER);
        eq("no slots are selected", panel.slots.length, 0);
        eq("the user is told why", toasts.length, 1);
        selectOnChart(T0, T0 + MAX_DRAFT_SLOTS * QUARTER);
        eq("the maximum itself is allowed", panel.slots.length, MAX_DRAFT_SLOTS);
        """)
