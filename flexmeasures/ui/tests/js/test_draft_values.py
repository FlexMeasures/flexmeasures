"""Tests for flexmeasures/ui/static/js/draft-values.js."""

# A panel with every element wireDraftValuesPanel looks for, and a chart that records what the panel asks of it.
PANEL = """
import { wireDraftValuesPanel, DRAFT_VALUES_RECORDED_EVENT } from "/js/draft-values.js";
document.body.insertAdjacentHTML("beforeend", `
  <div id="panel">
    <div data-draft-unavailable class="d-none"></div>
    <div data-draft-controls>
      <a href="#" data-draft-draw><span data-draft-draw-text>Draw on chart</span></a>
      <div data-draft-drawing class="d-none"><input data-draft-draw-max type="number" /></div>
      <a href="#" data-draft-record><span data-draft-record-text>Select on chart</span></a>
      <div data-draft-typed>
      <input data-draft-start type="datetime-local" />
      <input data-draft-duration type="text" />
      <input data-draft-value type="number" />
      <button data-draft-add type="button" class="btn-light">Add</button>
      </div>
      <div data-draft-selection></div>
      <ul data-draft-list></ul>
      <span data-draft-count class="d-none"></span>
      <div data-draft-empty>None yet.</div>
      <a href="#" data-draft-cancel class="d-none">Discard</a>
      <button data-draft-save type="button">Save</button>
      <button data-draft-next type="button">Preview</button>
    </div>
  </div>`);
const root = document.getElementById("panel");
const button = (name) => root.querySelector("[data-draft-" + name + "]");
const chart = { selecting: false, selection: null, drafts: [] };
chart.startSelecting = () => { chart.selecting = true; };
chart.stopSelecting = () => { chart.selecting = false; };
chart.showSelection = (range) => { chart.selection = range; };
chart.showDrafts = (drafts) => { chart.drafts = drafts; };
chart.drawing = false;
chart.scales = [];
chart.startDrawing = () => { chart.drawing = true; };
chart.stopDrawing = () => { chart.drawing = false; };
chart.getYAxisMax = () => 10;
chart.setDrawScale = (yMax) => chart.scales.push(yMax);
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
// Typing a start or a duration may start recording first, so the selection follows a moment later.
const typeIn = async (name, text) => {
  button(name).value = text;
  button(name).dispatchEvent(new Event("change"));
  await new Promise((resolve) => setTimeout(resolve, 0));
};
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
    """Select on chart turns on the select tool, a selection plus a value adds draft values, stopping keeps them, and Preview hands them over."""
    assert_js(PANEL + """
        eq("the panel starts idle", button("record").textContent, "Select on chart");
        typeValue("2");
        check("typing a value turns Add green, before a range is chosen", button("add").classList.contains("btn-success") && button("add").style.opacity === "1", "");
        check("though it waits for the range", button("add").disabled, "");
        typeValue("");
        check("clearing it takes the green away", button("add").classList.contains("btn-light"), "");
        selectOnChart(T0, T0 + 3600000);
        eq("a selection is ignored until recording", panel.slots.length, 0);

        button("record").click();
        await Promise.resolve();
        check("Select on chart turns on the select tool", chart.selecting, "");
        eq("and offers to stop selecting", button("record").textContent, "Stop selecting");

        selectOnChart(T0 + 60000, T0 + 3600000 - 60000);
        eq("a selection picks the slots it touches", panel.slots.length, 4);
        eq("the chart shows the snapped selection", chart.selection.end.getTime(), T0 + 3600000);
        check("Add waits for a value", button("add").disabled, "");
        check("and does not stand out yet", button("add").classList.contains("btn-light") && !button("add").classList.contains("btn-success"), "");
        typeValue("abc");
        check("nor for something that is not a number", button("add").classList.contains("btn-light"), "");
        typeValue("3.5");
        check("Add is offered with a selection and a value", !button("add").disabled, "");
        check("and turns green", button("add").classList.contains("btn-success") && !button("add").classList.contains("btn-light"), "");
        button("add").click();
        eq("every slot got the value", panel.drafts.map((d) => d.value), [3.5, 3.5, 3.5, 3.5]);
        eq("the chart shows the draft values", chart.drafts.length, 4);
        eq("the panel lists them in one row, as they are one run of the same value", button("list").children.length, 1);
        check("which has the value, its unit and the count", button("list").children[0].textContent.includes("3.5 kWh · 4 values"), button("list").children[0].textContent);
        eq("and counts them", [button("count").textContent, button("count").classList.contains("d-none")], ["4", false]);
        check("they can be discarded", !button("cancel").classList.contains("d-none"), "");
        eq("the selection is cleared", chart.selection, null);
        eq("the value stays for the next selection", button("value").value, "3.5");
        check("Add stays green, showing values were added", button("add").classList.contains("btn-success"), "");
        eq("not faded, though there is nothing to add for now", [button("add").disabled, button("add").style.opacity], [true, "1"]);

        selectOnChart(T0 + 3600000, T0 + 3600000 + 2 * QUARTER - 60000);
        typeValue("5");
        button("add").click();
        eq("another value makes another row", button("list").children.length, 2);
        selectOnChart(T0 + 3600000 + 2 * QUARTER, T0 + 3600000 + 3 * QUARTER - 60000);
        button("add").click();
        eq("and so does the same value after it, as one run", button("list").children.length, 2);
        button("list").children[1].querySelector("button").click();
        eq("a row's remove button removes that run", panel.drafts.map((d) => d.value), [3.5, 3.5, 3.5, 3.5]);
        button("list").children[0].querySelector("button").click();
        selectOnChart(T0, T0 + 3 * QUARTER - 60000);
        typeValue("3.5");
        button("add").click();

        button("record").click();
        check("stopping turns off the select tool", !chart.selecting, "");
        eq("Select on chart is offered again", button("record").textContent, "Select on chart");
        eq("the draft values are kept", panel.drafts.length, 3);
        eq("but not handed over", handedOver.length, 0);
        button("next").click();
        eq("Preview hands them over once", handedOver.length, 1);
        eq("to be previewed", handedOver[0].action, "preview");
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
        typeValue("");
        check("and with no value left, Add is no longer green", button("add").classList.contains("btn-light") && !button("add").classList.contains("btn-success"), "");
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
        panel.next();
        check("so it does after handing them over, since nothing was saved", leave(), "");
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


def test_durations_are_read_as_the_api_reads_them(assert_js):
    assert_js("""
        import { parseIsoDuration, formatIsoDuration } from "/js/draft-values.js";
        const HOUR = 3600000;
        eq("hours", parseIsoDuration("PT2H"), { months: 0, ms: 2 * HOUR });
        eq("minutes", parseIsoDuration("PT15M"), { months: 0, ms: 15 * 60000 });
        eq("a day is a fixed 24 hours", parseIsoDuration("P1D"), { months: 0, ms: 24 * HOUR });
        eq("a week is seven fixed days", parseIsoDuration("P1W"), { months: 0, ms: 7 * 24 * HOUR });
        eq("days and time combine", parseIsoDuration("P1DT1H30M"), { months: 0, ms: 25.5 * HOUR });
        eq("a fraction that makes whole minutes is accepted", parseIsoDuration("PT1.5H"), { months: 0, ms: 1.5 * HOUR });
        eq("months stay on the calendar", parseIsoDuration("P1Y2M"), { months: 14, ms: 0 });
        eq("lower case is forgiven", parseIsoDuration(" pt2h "), { months: 0, ms: 2 * HOUR });
        eq("a zero duration is a duration", parseIsoDuration("PT0M"), { months: 0, ms: 0 });
        eq("seconds that make no whole minute are refused, as by the API", parseIsoDuration("PT30S"), null);
        eq("a bare P is refused", parseIsoDuration("P"), null);
        eq("a T without time is refused", parseIsoDuration("P1DT"), null);
        eq("plain words are refused", parseIsoDuration("2 hours"), null);
        eq("nothing is refused", parseIsoDuration(""), null);

        eq("two hours are written as PT2H", formatIsoDuration(2 * HOUR), "PT2H");
        eq("a quarter as PT15M", formatIsoDuration(15 * 60000), "PT15M");
        eq("24 hours as P1D", formatIsoDuration(24 * HOUR), "P1D");
        eq("25 hours as P1DT1H", formatIsoDuration(25 * HOUR), "P1DT1H");
        eq("nothing as PT0M", formatIsoDuration(0), "PT0M");
        """)


def test_start_and_duration_over_dst_transitions(assert_js):
    """A day is 24 hours, as in the API, and months keep the start's UTC offset, as the API does."""
    assert_js(
        """
        import { rangeFromStartAndDuration, parseIsoDuration, toDatetimeLocalValue } from "/js/draft-values.js";
        const range = (start, text) => rangeFromStartAndDuration(new Date(start), parseIsoDuration(text));

        const autumn = range("2026-10-25T00:00", "P1D");
        eq("P1D from midnight on the 25-hour day ends at 23:00 local time", toDatetimeLocalValue(autumn.end), "2026-10-25T23:00");
        eq("which is 24 hours later", autumn.end - autumn.start, 24 * 3600000);

        const spring = range("2026-03-29T00:00", "PT3H");
        eq("three hours over the spring transition end at 04:00 local time", toDatetimeLocalValue(spring.end), "2026-03-29T04:00");

        const month = range("2026-03-15T10:00", "P1M");
        eq("a month from winter time ends on the same day of the next month", month.end.toISOString(), "2026-04-15T09:00:00.000Z");
        eq("at the start's UTC offset, as the API counts it", toDatetimeLocalValue(month.end), "2026-04-15T11:00");
        eq("the start is a local time", toDatetimeLocalValue(new Date("2026-10-25T01:30")), "2026-10-25T01:30");
        """,
        timezone="Europe/Amsterdam",
    )


def test_a_typed_start_and_duration_select_slots(assert_js):
    """Typing a start and a duration selects the slots they cover, and a selection on the chart fills both in."""
    assert_js(PANEL + """
        import { toDatetimeLocalValue } from "/js/draft-values.js";
        const start = new Date(T0 + 2 * 3600000 + 7 * 60000);
        await typeIn("start", toDatetimeLocalValue(start));
        eq("a start alone selects nothing", panel.slots.length, 0);
        check("nor starts recording", !panel.recording, "");
        await typeIn("duration", "PT1H");
        check("start and duration start recording, without pressing Select on chart", panel.recording && chart.selecting, "");
        eq("start and duration select the slots they touch", panel.slots.length, 5);
        eq("from the slot the start lies in", panel.slots[0].start.getTime(), T0 + 2 * 3600000);
        check("which shows on the chart", chart.selection && chart.selection.start.getTime() === T0 + 2 * 3600000, "");
        eq("the fields show the snapped start", button("start").value, toDatetimeLocalValue(new Date(T0 + 2 * 3600000)));
        eq("and the duration it covers", button("duration").value, "PT1H15M");

        await typeIn("duration", "two hours");
        check("an unreadable duration is pointed out", button("duration").classList.contains("is-invalid"), "");
        eq("and keeps the previous selection", panel.slots.length, 5);

        selectOnChart(T0, T0 + 30 * 60000);
        eq("a selection on the chart fills in the start", button("start").value, toDatetimeLocalValue(new Date(T0)));
        eq("and the duration", button("duration").value, "PT30M");
        check("and clears the complaint", !button("duration").classList.contains("is-invalid"), "");

        typeValue("4");
        panel.add();
        eq("adding fills the slots", panel.drafts.length, 2);
        eq("and clears the fields for the next range", [button("start").value, button("duration").value], ["", ""]);
        """)


def test_save_and_preview_add_what_is_pending_and_need_draft_values(assert_js):
    """Save and Preview wait for draft values, and add a selection with a value that was not added yet before handing over."""
    assert_js(PANEL + """
        check("with nothing drafted, there is nothing to save or preview", button("save").disabled && button("next").disabled, "");
        await panel.record();
        selectOnChart(T0, T0 + 3600000 - 60000);
        check("nor with a selection alone", button("save").disabled && button("next").disabled, "");
        typeValue("7");
        check("a selection with a value is enough", !button("save").disabled && !button("next").disabled, "");
        button("save").click();
        eq("it is added before handing over", handedOver.length, 1);
        eq("with every slot", handedOver[0].drafts.map((d) => d.value), [7, 7, 7, 7]);
        eq("to be saved as they are", handedOver[0].action, "save");
        check("and recording ends", !panel.recording && !chart.selecting, "");
        """)


def test_draft_values_are_grouped_into_runs(assert_js):
    assert_js("""
        import { groupDrafts, removeDraftsIn } from "/js/draft-values.js";
        const Q = 15 * 60 * 1000;
        const T0 = Date.UTC(2026, 0, 1);
        const slot = (k, value) => ({ start: new Date(T0 + k * Q), end: new Date(T0 + (k + 1) * Q), value: value });
        const drafts = [slot(0, 1), slot(1, 1), slot(2, 2), slot(4, 2), slot(5, 2)];
        const groups = groupDrafts(drafts);
        eq("adjacent slots with the same value make one group, a new value or a gap another",
           groups.map((g) => [g.start.getTime() - T0, g.end.getTime() - T0, g.value, g.count]),
           [[0, 2 * Q, 1, 2], [2 * Q, 3 * Q, 2, 1], [4 * Q, 6 * Q, 2, 2]]);
        eq("nothing makes no groups", groupDrafts([]), []);
        eq("a group can be removed by its range", removeDraftsIn(drafts, T0 + 4 * Q, T0 + 6 * Q).length, 3);
        """)


def test_a_stroke_becomes_draft_values(assert_js):
    """Each slot a stroke crosses takes the stroke's height at its middle, rounded to the step the drawing can tell apart."""
    assert_js("""
        import { strokeToDrafts } from "/js/draft-values.js";
        const Q = 15 * 60 * 1000;
        const T0 = Date.UTC(2026, 0, 1);
        const at = (minutes, value) => ({ time: new Date(T0 + minutes * 60000), value: value });
        const level = strokeToDrafts([at(2, 20.3), at(58, 19.8)], Q, T0, 1);
        eq("a level line over an hour makes four values, at its rounded height",
           level.map((d) => [d.start.getTime() - T0, d.value]), [[0, 20], [Q, 20], [2 * Q, 20], [3 * Q, 20]]);
        const ramp = strokeToDrafts([at(0, 0), at(60, 40)], Q, T0);
        eq("a ramp is read at the middle of each slot", ramp.map((d) => d.value), [5, 15, 25, 35]);
        // Along at 10, up at the end, and back along at 30.
        const back = strokeToDrafts([at(0, 10), at(60, 10), at(60, 30), at(30, 30)], Q, T0);
        eq("where the stroke passes twice, the last pass counts", back.map((d) => d.value), [10, 10, 30, 30]);
        eq("a click makes the one slot it is in", strokeToDrafts([at(20, 7)], Q, T0).map((d) => [d.start.getTime() - T0, d.value]), [[Q, 7]]);
        eq("decimals follow the step", strokeToDrafts([at(5, 0.12345)], Q, T0, 0.01)[0].value, 0.12);
        eq("nothing drawn makes nothing", strokeToDrafts([], Q, T0), []);
        """)


def test_the_scale_to_draw_on(assert_js):
    assert_js("""
        import { proposedDrawScale } from "/js/draft-values.js";
        import { drawnValueStep } from "/js/fast-chart.js";
        eq("twice the axis, rounded up to one significant digit", [proposedDrawScale(10), proposedDrawScale(37), proposedDrawScale(0.3)], [20, 80, 1]);
        eq("an empty chart still gets room", proposedDrawScale(null), 1);
        eq("values are worth a power of ten no finer than a pixel", [drawnValueStep(0.27), drawnValueStep(0.004), drawnValueStep(3)], [1, 0.01, 10]);
        """)


def test_drawing_on_the_chart_makes_draft_values(assert_js):
    """Draw turns on the draw tool with a scale above the data, a drawn stroke adds draft values, and other tools end it."""
    assert_js(PANEL + """
        const Q = QUARTER;
        const stroke = (fromMin, toMin, value) => target.dispatchEvent(new CustomEvent("chartdrawn", {
          detail: { points: [{ time: new Date(T0 + fromMin * 60000), value: value }, { time: new Date(T0 + toMin * 60000), value: value }], step: 1 },
        }));
        stroke(0, 59, 20);
        eq("a stroke is ignored until drawing", panel.drafts.length, 0);
        await panel.record();
        button("draw").click();
        await Promise.resolve();
        check("Draw turns on the draw tool", chart.drawing && panel.drawing, "");
        check("ending selecting", !panel.recording && !chart.selecting, "");
        eq("and offers to stop", button("draw").textContent, "Stop drawing");
        check("explaining how, and hiding the typed fields", !button("drawing").classList.contains("d-none") && button("typed").classList.contains("d-none"), "");
        eq("proposing a scale above the data", [button("draw-max").value, chart.scales], ["20", [20]]);
        button("draw-max").value = "50";
        button("draw-max").dispatchEvent(new Event("change"));
        eq("which can be changed", chart.scales, [20, 50]);

        stroke(0, 59, 20);
        eq("a stroke adds a draft value per slot", panel.drafts.map((d) => d.value), [20, 20, 20, 20]);
        eq("shown on the chart", chart.drafts.length, 4);
        stroke(30, 59, 40);
        eq("drawing again over a part changes it", panel.drafts.map((d) => d.value), [20, 20, 40, 40]);
        check("they can be saved or previewed", !button("save").disabled && !button("next").disabled, "");

        await panel.record();
        check("selecting ends drawing", !panel.drawing && !chart.drawing && chart.selecting, "");
        check("and brings the typed fields back", !button("typed").classList.contains("d-none"), "");
        panel.endRecording();
        button("draw").click();
        await Promise.resolve();
        target.dispatchEvent(new CustomEvent("chartdrawmodeended"));
        check("another chart tool ends drawing too", !panel.drawing && button("draw").textContent === "Draw on chart", "");
        """)
