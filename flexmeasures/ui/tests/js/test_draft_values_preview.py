"""Tests for flexmeasures/ui/static/js/draft-values-preview.js."""

import json

# A report as the recurrence preview endpoint returns it, for 15-minute values repeated daily in Europe/Amsterdam,
# over both transitions of a pattern covering 01:00-04:00 (four slots per hour, all with a value).
SPRING_FORWARD = dict(
    date="2027-03-28",
    kind="spring_forward",
    shift="PT1H",
    wall_clock_start="02:00",
    wall_clock_end="03:00",
    omitted=["02:00", "02:15", "02:30", "02:45"],
    duplicated=[],
    n_omitted=4,
    n_duplicated=0,
)
FALL_BACK = dict(
    date="2026-10-25",
    kind="fall_back",
    shift="PT1H",
    wall_clock_start="02:00",
    wall_clock_end="03:00",
    omitted=[],
    duplicated=["02:00", "02:15", "02:30", "02:45"],
    n_omitted=0,
    n_duplicated=4,
)

# A panel step with every element wirePreviewStep looks for, an API that records its requests and answers as told,
# and a chart that records what the step asks of it.
STEP = """
import { wirePreviewStep } from "/js/draft-values-preview.js";
import { DRAFT_VALUES_RECORDED_EVENT } from "/js/draft-values.js";
document.body.insertAdjacentHTML("beforeend", `
  <div id="step">
    <div data-preview-summary></div>
    <input data-preview-repeat type="radio" name="repeat" value="none" checked />
    <input data-preview-repeat type="radio" name="repeat" value="daily" />
    <input data-preview-repeat type="radio" name="repeat" value="same-weekday" />
    <input data-preview-until type="date" />
    <button data-preview-run type="button">Preview</button>
    <div data-preview-error class="d-none"></div>
    <div data-preview-result class="d-none">
      <span data-preview-create></span><span data-preview-omitted></span>
      <span data-preview-duplicated></span><span data-preview-superseded></span>
      <ul data-preview-warnings></ul>
      <button data-preview-show-all type="button"></button>
      <button data-preview-show-drafts type="button"></button>
    </div>
    <button data-preview-back type="button"></button>
    <button data-preview-discard type="button"></button>
    <button data-preview-confirm type="button"></button>
  </div>`);
const root = document.getElementById("step");
const part = (name) => root.querySelector("[data-preview-" + name + "]");
const HOUR = 3600 * 1000;
const QUARTER = HOUR / 4;
const T0 = Date.UTC(2026, 10, 2, 5, 0); // 2 November 2026, 06:00 in Amsterdam
const drafts = [0, 1, 2, 3].map((k) => ({ start: new Date(T0 + k * QUARTER), end: new Date(T0 + (k + 1) * QUARTER), value: 80 + k }));

const calls = { preview: [], fetchExisting: [], save: [] };
const answers = { preview: null, fetchExisting: null, save: null };
const api = {};
for (const name of Object.keys(calls)) {
  api[name] = (arg) => {
    calls[name].push(arg);
    return Promise.resolve(typeof answers[name] === "function" ? answers[name](arg) : answers[name]);
  };
}
const ok = (body, status) => ({ ok: true, status: status || 200, body: body });
const noExistingData = (query) => ok({ start: query.get("start"), values: [] });
answers.fetchExisting = noExistingData;
answers.save = ok({ status: "PROCESSED" });

const chart = { previews: [], windows: [], reloads: 0, window: { start: new Date(T0 - 2 * 24 * HOUR), end: new Date(T0 + 24 * HOUR) } };
chart.showPreview = (preview) => chart.previews.push(preview);
chart.getWindow = () => chart.window;
chart.setWindow = (range) => { chart.windows.push(range); chart.window = range; };
chart.reload = () => { chart.reloads++; };
const draftStep = { discarded: 0, discard: () => { draftStep.discarded++; } };
const visible = [];
const confirmations = [];
let confirmAnswer = true;
const notes = [];
const target = new EventTarget();
const step = wirePreviewStep(root, {
  sensorId: 42, resolutionMs: QUARTER, unit: "kWh", timeZone: "Europe/Amsterdam",
  api: api, chart: chart, drafts: draftStep, target: target,
  setVisible: (shown) => visible.push(shown),
  confirm: (message) => { confirmations.push(message); return confirmAnswer; },
  notify: (message, type) => notes.push([message, type]),
  formatTime: (date) => date.toISOString(),
  formatDate: (isoDate) => isoDate,
});
const handOver = (sensorId, handed) =>
  target.dispatchEvent(new CustomEvent(DRAFT_VALUES_RECORDED_EVENT, { detail: { sensorId: sensorId, drafts: handed } }));
const choose = (repeat) => {
  const input = root.querySelector(`[data-preview-repeat][value="${repeat}"]`);
  input.checked = true;
  input.dispatchEvent(new Event("change"));
};
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const click = async (name) => { part(name).click(); await settle(); };
"""


def test_until_bounds_follow_the_sensor_timezone(assert_js):
    """The earliest date is the first repeat, the latest one year on, and the default one week on, all on the sensor's calendar."""
    assert_js("""
        import { untilBounds, localDate } from "/js/draft-values-preview.js";
        // 23:30 UTC on 24 October is already 25 October in Amsterdam.
        const drafts = [{ start: new Date(Date.UTC(2026, 9, 24, 23, 30)), end: new Date(Date.UTC(2026, 9, 25, 0, 0)), value: 1 }];
        eq("the local date is read in the sensor's timezone", localDate(drafts[0].start, "Europe/Amsterdam"), "2026-10-25");
        eq("daily repeats run from the next day, for a week by default, up to a year",
           untilBounds(drafts, "Europe/Amsterdam", "daily"), { min: "2026-10-26", max: "2027-10-25", default: "2026-11-01" });
        eq("repeats on the same weekday start a week later",
           untilBounds(drafts, "Europe/Amsterdam", "same-weekday"), { min: "2026-11-01", max: "2027-10-25", default: "2026-11-01" });
        eq("in UTC, the same drafts start a day earlier",
           untilBounds(drafts, "UTC", "daily").min, "2026-10-25");
        const leap = [{ start: new Date(Date.UTC(2028, 1, 29, 12)), end: new Date(Date.UTC(2028, 1, 29, 13)), value: 1 }];
        eq("a year after 29 February is 28 February, as the endpoint counts it", untilBounds(leap, "UTC", "daily").max, "2029-02-28");
        """)


def test_draft_values_become_one_pattern_with_gaps(assert_js):
    assert_js("""
        import { draftsToPattern, previewRequestBody, PreviewError } from "/js/draft-values-preview.js";
        const HOUR = 3600 * 1000;
        const t0 = Date.UTC(2026, 10, 2, 5, 0);
        const slot = (h, value) => ({ start: new Date(t0 + h * HOUR), end: new Date(t0 + (h + 1) * HOUR), value: value });
        const pattern = draftsToPattern([slot(0, 80), slot(1, 90), slot(4, 70)], HOUR, "kWh");
        eq("the pattern holds every slot from the first draft value to the last, with null between them",
           pattern, { start: "2026-11-02T05:00:00Z", duration: "PT5H", values: [80, 90, null, null, 70], unit: "kWh" });
        eq("the preview request adds the repetition to the pattern",
           previewRequestBody(pattern, "daily", "2026-11-09"),
           { start: "2026-11-02T05:00:00Z", duration: "PT5H", values: [80, 90, null, null, 70], unit: "kWh", repeat: "daily", until: "2026-11-09" });
        let refused = null;
        try { draftsToPattern([], HOUR, "kWh"); } catch (e) { refused = e; }
        check("no draft values are refused", refused instanceof PreviewError, String(refused));
        """)


def test_daily_draft_values_across_a_clock_change_are_refused(assert_js):
    """Posted values are laid out in fixed steps, which local days around a clock change are not."""
    assert_js(
        """
        import { draftsToPattern, PreviewError } from "/js/draft-values-preview.js";
        const DAY = 24 * 3600 * 1000;
        const day = (d) => ({ start: new Date(2026, 9, d), end: new Date(2026, 9, d + 1), value: d });
        eq("days before the transition are one pattern", draftsToPattern([day(23), day(24)], DAY, "kWh").values, [23, 24]);
        let refused = null;
        try { draftsToPattern([day(24), day(25), day(26)], DAY, "kWh"); } catch (e) { refused = e; }
        check("days across the transition are refused", refused instanceof PreviewError, String(refused));
        check("with a reason that names the transition", /daylight saving time/.test(refused && refused.message), String(refused));
        """,
        timezone="Europe/Amsterdam",
    )


def test_saving_adds_the_repeats_after_the_pattern(assert_js):
    """The preview leaves out the pattern, so it is put back in front of the repeats, with null values up to the first one."""
    assert_js("""
        import { draftsToPattern, payloadForSaving, gridToPoints, PreviewError } from "/js/draft-values-preview.js";
        const HOUR = 3600 * 1000;
        const t0 = Date.UTC(2026, 10, 2, 5, 0);
        const pattern = { start: "2026-11-02T05:00:00Z", duration: "PT2H", values: [80, 90], unit: "kWh" };
        eq("without repeats, the pattern is saved as it is", payloadForSaving(pattern, null, HOUR), pattern);
        // As the endpoint answers, in the sensor's timezone: the next day at 06:00.
        const repeats = { start: "2026-11-03T06:00:00+01:00", duration: "PT26H", values: [80, 90].concat(new Array(22).fill(null), [80, 90]), unit: "kWh" };
        const payload = payloadForSaving(pattern, repeats, HOUR);
        eq("the body starts at the pattern", payload.start, pattern.start);
        eq("and runs to the end of the last repeat", payload.duration, "P2DT2H");
        eq("the pattern comes first, then null up to the first repeat, then the repeats unchanged",
           payload.values, [80, 90].concat(new Array(22).fill(null), repeats.values));
        eq("so the values land where the preview put them",
           gridToPoints(payload, HOUR).map((p) => (p.start.getTime() - t0) / HOUR), [0, 1, 24, 25, 48, 49]);
        let refused = null;
        try { payloadForSaving(pattern, { ...repeats, start: "2026-11-03T06:30:00+01:00" }, HOUR); } catch (e) { refused = e; }
        check("repeats off the pattern's grid are refused", refused instanceof PreviewError, String(refused));
        """)


def test_grid_to_points_leaves_out_null_values(assert_js):
    assert_js("""
        import { gridToPoints } from "/js/draft-values-preview.js";
        const QUARTER = 15 * 60 * 1000;
        const points = gridToPoints({ start: "2026-10-25T02:00:00+02:00", values: [1, null, 0, null] }, QUARTER);
        eq("only slots with a value are kept, zero included", points.map((p) => p.value), [1, 0]);
        eq("each at its place in the series", points.map((p) => p.start.toISOString()), ["2026-10-25T00:00:00.000Z", "2026-10-25T00:30:00.000Z"]);
        eq("lasting one step", points[1].end - points[1].start, QUARTER);
        """)


def test_overlaps_are_the_existing_values_under_new_ones(assert_js):
    assert_js("""
        import { findOverlaps } from "/js/draft-values-preview.js";
        const HOUR = 3600 * 1000;
        const slot = (h, value, hours) => ({ start: new Date(h * HOUR), end: new Date((h + (hours || 1)) * HOUR), value: value });
        const proposed = [slot(1, 10), slot(2, 20), slot(5, 50)];
        const existing = [slot(0, 1), slot(2, 2), slot(3, 3), slot(5, 5), slot(6, 6)];
        eq("only existing values at times that get a new value overlap",
           findOverlaps(proposed, existing).map((o) => [o.start.getTime() / HOUR, o.existing, o.proposed]), [[2, 2, 20], [5, 5, 50]]);
        eq("nothing overlaps without existing values", findOverlaps(proposed, []).length, 0);
        eq("nor without new ones", findOverlaps([], existing).length, 0);
        eq("a longer existing slot overlaps every new value it covers once",
           findOverlaps(proposed, [slot(0, 7, 3)]).map((o) => o.proposed), [10]);
        """)


def test_the_report_becomes_counts_and_warnings(assert_js):
    assert_js(f"""
        import {{ summarizePreview, transitionWarning }} from "/js/draft-values-preview.js";
        const spring = {json.dumps(SPRING_FORWARD)};
        const fall = {json.dumps(FALL_BACK)};
        const formatDate = (isoDate) => isoDate;
        const report = {{ n_values: 1916, n_omitted: 4, n_duplicated: 4, mode: "wall_clock", period: "daily", n_occurrences: 160,
                          transitions: [fall, spring], fallback_reason: null }};
        const summary = summarizePreview(report, 12, {{ formatDate }});
        eq("the draft values count among the values to create", summary.toCreate, 1928);
        eq("omitted and duplicated values come from the report", [summary.omitted, summary.duplicated], [4, 4]);
        eq("each transition gives a warning", summary.warnings, [
          "On 2026-10-25 02:00–03:00 occurs twice: those 4 values will be written to both.",
          "On 2027-03-28 the clock skips 02:00–03:00: 4 values will not be written.",
        ]);
        eq("one value is spoken of in the singular",
           transitionWarning({{ ...spring, n_omitted: 1 }}, {{ formatDate }}), "On 2027-03-28 the clock skips 02:00–03:00: 1 value will not be written.");
        eq("a transition that affects no value gives no warning", transitionWarning({{ ...fall, n_duplicated: 0 }}, {{ formatDate }}), null);
        const absolute = {{ ...report, mode: "absolute", transitions: [], fallback_reason: "Values are repeated every 24 hours instead." }};
        eq("a fallback to fixed steps is a warning too", summarizePreview(absolute, 1, {{ formatDate }}).warnings, ["Values are repeated every 24 hours instead."]);
        eq("without repeats, the draft values are all there is", summarizePreview(null, 12),
           {{ toCreate: 12, omitted: 0, duplicated: 0, warnings: [] }});
        check("dates are shown readably by default", /2026/.test(transitionWarning(fall)) && !/2026-10-25/.test(transitionWarning(fall)), transitionWarning(fall));
        """)


def test_error_text_is_plain(assert_js):
    assert_js("""
        import { errorText } from "/js/draft-values-preview.js";
        const refusal = { ok: false, status: 422, body: { message: { json: { until: ["Repeat until 2027-11-02 at the latest."] } } } };
        eq("a field error names its field, without markup", errorText(refusal), "until: Repeat until 2027-11-02 at the latest.");
        eq("a plain message is kept", errorText({ ok: false, status: 422, body: { message: "The pattern spans P1DT1H." } }), "The pattern spans P1DT1H.");
        check("without a body, the status is given", /500/.test(errorText({ ok: false, status: 500, body: null })), "");
        """)


def test_the_step_opens_on_the_hand_off_of_draft_values(assert_js):
    assert_js(STEP + """
        handOver(42, []);
        eq("no draft values, no step", visible, []);
        handOver(7, drafts);
        eq("another sensor's draft values are not picked up", visible, []);
        handOver(42, drafts);
        eq("draft values open the step", visible, [true]);
        check("describing them", part("summary").textContent.startsWith("4 draft values"), part("summary").textContent);
        check("starting with no repetition, so no date", part("until").disabled, "");
        check("nothing to confirm yet", part("confirm").disabled, "");
        choose("daily");
        eq("a repetition proposes a date a week on", part("until").value, "2026-11-09");
        eq("between its bounds", [part("until").min, part("until").max], ["2026-11-03", "2027-11-02"]);
        """)


def test_previewing_without_repetition_saves_the_draft_values(assert_js):
    assert_js(STEP + """
        handOver(42, drafts);
        await click("run");
        eq("no repetition needs no preview from the server", calls.preview.length, 0);
        eq("the existing values are loaded once, over the draft values",
           calls.fetchExisting.map((q) => q.toString()), ["start=2026-11-02T05%3A00%3A00Z&duration=PT1H&unit=kWh"]);
        eq("the draft values are to be created", part("create").textContent, "4");
        check("and shown on the chart", chart.previews.length === 1 && chart.previews[0].points.length === 4, JSON.stringify(chart.previews));
        check("which shows them all", chart.windows.length === 1, "");
        check("they can be confirmed", !part("confirm").disabled, "");
        await click("confirm");
        eq("confirming posts them", calls.save, [{ start: "2026-11-02T05:00:00Z", duration: "PT1H", values: [80, 81, 82, 83], unit: "kWh" }]);
        eq("says so", notes, [["Saved.", "success"]]);
        eq("clears the draft values", draftStep.discarded, 1);
        eq("closes the step", visible, [true, false]);
        eq("and reloads the chart", chart.reloads, 1);
        eq("the overlay is gone", chart.previews[chart.previews.length - 1], null);
        """)


def test_previewing_daily_repeats_and_confirming_them(assert_js):
    """The repeats come from the endpoint, the counts and warnings from its report, and the overlaps from the existing data."""
    assert_js(STEP + f"""
        // Repeats the next day only, as the endpoint answers: in the sensor's timezone.
        const repeats = {{ start: "2026-11-03T06:00:00+01:00", duration: "PT1H", values: [80, 81, 82, 83], unit: "kWh" }};
        const report = {{ n_values: 4, n_omitted: 0, n_duplicated: 4, mode: "wall_clock", period: "daily", n_occurrences: 1,
                          transitions: [{json.dumps(FALL_BACK)}], fallback_reason: null }};
        answers.preview = ok({{ data: repeats, report: report }});
        // Existing values at the second draft value, and at the first repeat.
        answers.fetchExisting = (query) => {{
          const values = new Array(100).fill(null);
          values[1] = 50;
          values[96] = 60;
          return ok({{ start: query.get("start"), values: values }});
        }};
        answers.save = ok({{ status: "PROCESSED" }}, 202);
        handOver(42, drafts);
        choose("daily");
        part("until").value = "2026-11-03";
        part("until").dispatchEvent(new Event("change"));
        await click("run");
        eq("the pattern is sent with its repetition", calls.preview, [{{
          start: "2026-11-02T05:00:00Z", duration: "PT1H", values: [80, 81, 82, 83], unit: "kWh", repeat: "daily", until: "2026-11-03",
        }}]);
        eq("the existing values are loaded over the whole range, once",
           calls.fetchExisting.map((q) => q.get("duration")), ["P1DT1H"]);
        eq("the counts", ["create", "omitted", "duplicated", "superseded"].map((name) => part(name).textContent), ["8", "0", "4", "2"]);
        eq("the warning", Array.from(part("warnings").children).map((li) => li.textContent),
           ["On 2026-10-25 02:00–03:00 occurs twice: those 4 values will be written to both."]);
        eq("the superseded values are highlighted", chart.previews[chart.previews.length - 1].superseded.map((o) => o.existing), [50, 60]);
        const whole = chart.windows[chart.windows.length - 1];
        eq("the chart shows the whole range", [whole.start.getTime(), whole.end.getTime()], [T0, T0 + 25 * HOUR]);
        await click("show-drafts");
        eq("and can go back to the window shown before", chart.window.start.getTime(), T0 - 2 * 24 * HOUR);
        await click("confirm");
        eq("confirming posts the pattern and its repeats in one body", calls.save.length, 1);
        eq("with the repeats unchanged at the end", calls.save[0].values.slice(-4), repeats.values);
        eq("and null in between", calls.save[0].values.slice(4, -4), new Array(92).fill(null));
        eq("a background save says the values come later", notes, [["Saved, values will appear shortly.", "success"]]);
        eq("and clears the draft values", draftStep.discarded, 1);
        """)


def test_a_refused_preview_shows_inline(assert_js):
    assert_js(STEP + """
        answers.preview = { ok: false, status: 422, body: { message: "The pattern spans P1DT1H of local time, which is longer than the recurrence period of P1D." } };
        handOver(42, drafts);
        choose("daily");
        await click("run");
        check("the endpoint's reason shows in the step", part("error").textContent.includes("longer than the recurrence period"), part("error").textContent);
        check("visibly", !part("error").classList.contains("d-none"), "");
        check("there is nothing to confirm", part("confirm").disabled, "");
        eq("and nothing is shown on the chart", chart.previews.filter(Boolean).length, 0);
        """)


def test_changing_the_repetition_takes_the_preview_away(assert_js):
    assert_js(STEP + """
        handOver(42, drafts);
        await click("run");
        check("previewed", !part("confirm").disabled, "");
        choose("daily");
        check("a new choice must be previewed before confirming", part("confirm").disabled, "");
        eq("and the old preview leaves the chart", chart.previews[chart.previews.length - 1], null);
        check("the result is hidden", part("result").classList.contains("d-none"), "");
        """)


def test_a_late_answer_for_an_old_choice_is_ignored(assert_js):
    assert_js(STEP + """
        let answerLate;
        answers.preview = () => new Promise((resolve) => { answerLate = resolve; });
        handOver(42, drafts);
        choose("daily");
        part("run").click();
        choose("same-weekday");
        answerLate(ok({ data: { start: "2026-11-03T06:00:00+01:00", values: [1] }, report: { n_values: 1, n_omitted: 0, n_duplicated: 0, transitions: [] } }));
        await settle();
        eq("the answer to the old choice is not shown", step.result, null);
        check("nor can it be confirmed", part("confirm").disabled, "");
        """)


def test_back_to_edit_keeps_the_draft_values_and_saves_nothing(assert_js):
    assert_js(STEP + """
        handOver(42, drafts);
        await click("run");
        await click("back");
        eq("the step closes", visible, [true, false]);
        eq("the draft values are kept", draftStep.discarded, 0);
        eq("nothing is saved", calls.save.length, 0);
        eq("the chart goes back to the window shown before", chart.window.start.getTime(), T0 - 2 * 24 * HOUR);
        eq("without the preview", chart.previews[chart.previews.length - 1], null);
        """)


def test_discarding_asks_first_and_saves_nothing(assert_js):
    assert_js(STEP + """
        handOver(42, drafts);
        confirmAnswer = false;
        await click("discard");
        eq("discarding asks", confirmations, ["Discard 4 draft values? They have not been saved."]);
        eq("a no keeps everything", [draftStep.discarded, visible], [0, [true]]);
        confirmAnswer = true;
        await click("discard");
        eq("a yes discards the draft values", draftStep.discarded, 1);
        eq("and closes the step", visible, [true, false]);
        eq("nothing is saved", calls.save.length, 0);
        """)


def test_a_refused_save_keeps_the_draft_values(assert_js):
    assert_js(STEP + """
        answers.save = { ok: false, status: 403, body: { message: "You cannot be authorized for this content or functionality." } };
        handOver(42, drafts);
        await click("run");
        await click("confirm");
        check("the refusal shows in the step", part("error").textContent.startsWith("Nothing was saved: You cannot be authorized"), part("error").textContent);
        eq("the draft values are kept", draftStep.discarded, 0);
        eq("the step stays open", visible, [true]);
        check("so the user can try again", !part("confirm").disabled, "");
        """)
