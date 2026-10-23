"""Tests for flexmeasures/ui/static/js/chart-data-cache.js and chart-data-fetch.js.

The cache is exercised against a stand-in for `fetch`, which records what was asked for,
and answers with one record per hour of the window asked for, in the compressed format the API sends.
"""

# Installs the stand-in for `fetch`, and helpers to build dates and records.
# Hourly records for sensor 1, on UTC dates, so the tests do not depend on the browser's timezone.
FAKE_API = """
const requests = [];
const HOUR = 3600 * 1000;
window.fetch = async (url) => {
    requests.push(url);
    const query = new URLSearchParams(url.split("?")[1]);
    const start = new Date(query.get("event_starts_after")).getTime();
    const end = new Date(query.get("event_ends_before")).getTime();
    const data = [];
    for (let t = start; t < end; t += HOUR) data.push({sid: 1, src: 9, ts: t, val: t / HOUR, bh: 0, bt: t});
    return {json: async () => ({
        data: data,
        sensors: {1: {name: "power", unit: "kW", event_resolution: 3600}},
        sources: {9: {name: "meter", type: "user"}},
    })};
};
const day = (d) => new Date(Date.UTC(2022, 0, d));
const starts = (records) => records.map((r) => r.event_start);
const hoursBetween = (a, b) => (b - a) / HOUR;
"""


def test_missing_ranges(assert_js):
    assert_js("""
        import { missingRanges } from "/js/chart-data-cache.js";
        const day = (d) => new Date(Date.UTC(2022, 0, d));
        const loaded = {start: day(10), end: day(17)};
        eq("nothing loaded means everything is missing",
           missingRanges(day(1), day(3), null), [{start: day(1), end: day(3)}]);
        eq("a window inside the loaded one needs nothing", missingRanges(day(11), day(15), loaded), []);
        eq("stepping forward needs only the new tail",
           missingRanges(day(11), day(18), loaded), [{start: day(17), end: day(18)}]);
        eq("stepping back needs only the new head",
           missingRanges(day(9), day(16), loaded), [{start: day(9), end: day(10)}]);
        eq("widening on both sides needs a head and a tail",
           missingRanges(day(8), day(20), loaded),
           [{start: day(8), end: day(10)}, {start: day(17), end: day(20)}]);
        eq("a window that merely touches the loaded one is fetched whole",
           missingRanges(day(17), day(20), loaded), [{start: day(17), end: day(20)}]);
        eq("a window apart from the loaded one is fetched whole",
           missingRanges(day(1), day(3), loaded), [{start: day(1), end: day(3)}]);
        """)


def test_effective_resolution_is_the_finest_non_instantaneous_one(assert_js):
    assert_js("""
        import { effectiveResolutionMs } from "/js/chart-data-cache.js";
        const record = (seconds) => ({sensor: {event_resolution: seconds}});
        eq("the finest resolution wins", effectiveResolutionMs([record(3600), record(900)]), 900000);
        eq("instantaneous sensors are left out", effectiveResolutionMs([record(0), record(3600)]), 3600000);
        eq("only instantaneous sensors means zero", effectiveResolutionMs([record(0)]), 0);
        eq("no records means zero", effectiveResolutionMs([]), 0);
        eq("records without a sensor are skipped", effectiveResolutionMs([{}, record(60)]), 60000);
        eq("no records at all means zero", effectiveResolutionMs(undefined), 0);
        """)


def test_on_same_resampling_grid(assert_js):
    assert_js("""
        import { onSameResamplingGrid } from "/js/chart-data-cache.js";
        const t = (minutes) => new Date(Date.UTC(2022, 0, 1) + minutes * 60000);
        eq("whole hours are on an hourly grid", onSameResamplingGrid(t(0), t(120), t(600), 3600000), true);
        eq("a window starting off the grid is not",
           onSameResamplingGrid(t(0), t(30), t(600), 3600000), false);
        eq("a window ending off the grid is not", onSameResamplingGrid(t(0), t(60), t(610), 3600000), false);
        eq("7-minute steps do not line up with whole hours",
           onSameResamplingGrid(t(0), t(60), t(120), 7 * 60000), false);
        eq("without a resolution, anything goes", onSameResamplingGrid(t(0), t(7), t(13), 0), true);
        """)


def test_clip_to_window_keeps_events_overlapping_the_window(assert_js):
    """The API selects events that overlap the window, not just those starting inside it."""
    assert_js("""
        import { clipToWindow } from "/js/chart-data-cache.js";
        const HOUR = 3600000;
        const hourly = (h) => ({event_start: h * HOUR, sensor: {event_resolution: 3600}});
        const instant = (h) => ({event_start: h * HOUR, sensor: {event_resolution: 0}});
        const kept = (records, from, until, resolution) =>
            clipToWindow(records, new Date(from * HOUR), new Date(until * HOUR), resolution * HOUR)
            .map((r) => r.event_start / HOUR);
        eq("events inside [start, end) are kept", kept([hourly(1), hourly(2), hourly(3)], 1, 3, 1), [1, 2]);
        eq("an event running across the start is kept", kept([hourly(0)], 0.5, 3, 1), [0]);
        eq("an event ending exactly at the start is not", kept([hourly(0)], 1, 3, 1), []);
        eq("instantaneous events count on both edges", kept([instant(1), instant(3), instant(4)], 1, 3, 1), [1, 3]);
        eq("no records gives no records", clipToWindow(undefined, new Date(0), new Date(1), 1), []);
        """)


def test_dedupe_records(assert_js):
    assert_js("""
        import { dedupeRecords } from "/js/chart-data-cache.js";
        const record = (sensor, start, source, beliefTime, value) =>
            ({sensor: {id: sensor}, event_start: start, source: {id: source}, belief_time: beliefTime, event_value: value});
        const records = [
            record(1, 0, 9, 0, "first"),
            record(1, 0, 9, 0, "repeat"),
            record(2, 0, 9, 0, "other sensor"),
            record(1, 0, 8, 0, "other source"),
            record(1, 0, 9, 5, "other belief time"),
        ];
        eq("only the exact repeat is dropped, keeping the first",
           dedupeRecords(records).map((r) => r.event_value),
           ["first", "other sensor", "other source", "other belief time"]);
        """)


def test_build_chart_data_url(assert_js):
    assert_js("""
        import { buildChartDataUrl } from "/js/chart-data-fetch.js";
        const start = new Date(Date.UTC(2022, 0, 1));
        const end = new Date(Date.UTC(2022, 0, 2));
        eq("the window is sent in UTC, compressed",
           buildChartDataUrl("/api/v3_0/assets/1", {start, end}),
           "/api/v3_0/assets/1/chart_data?event_starts_after=2022-01-01T00:00:00.000Z"
           + "&event_ends_before=2022-01-02T00:00:00.000Z&compress_json=true");
        check("every belief is asked for only when explicitly wanted",
              buildChartDataUrl("/x", {start, end, mostRecentBeliefsOnly: false}).includes("most_recent_beliefs_only=false"));
        check("the default leaves it to the API",
              !buildChartDataUrl("/x", {start, end, mostRecentBeliefsOnly: true}).includes("most_recent_beliefs_only"));
        """)


def test_fetch_chart_data_decompresses_the_response(assert_js):
    assert_js(FAKE_API + """
        import { fetchChartData, fetchChartAnnotations } from "/js/chart-data-fetch.js";
        const records = await fetchChartData("/api/v3_0/sensors/1", {start: day(1), end: day(2)});
        eq("one record per hour of the day", records.length, 24);
        eq("records come back in the chart format", records[0].sensor.name, "power");

        window.fetch = async (url) => { requests.push(url); return {json: async () => [{content: "holiday"}]}; };
        const annotations = await fetchChartAnnotations("/api/v3_0/assets/1", {start: day(1), end: day(2)});
        eq("annotations are returned as sent", annotations, [{content: "holiday"}]);
        check("annotations are asked for the same window",
              requests.at(-1).startsWith("/api/v3_0/assets/1/chart_annotations?event_starts_after=2022-01-01T00:00:00.000Z"),
              requests.at(-1));
        """)


def test_cache_fetches_only_what_it_lacks(assert_js):
    assert_js(FAKE_API + """
        import { createChartDataCache } from "/js/chart-data-cache.js";
        const cache = createChartDataCache();

        let records = await cache.load("/s", {start: day(10), end: day(17)});
        eq("a first load fetches the whole week", requests.length, 1);
        eq("and returns every hour of it", records.length, 7 * 24);

        records = await cache.load("/s", {start: day(11), end: day(18)});
        eq("stepping a day forward fetches only that day", requests.length, 2);
        check("namely the new day", requests[1].includes("event_starts_after=2022-01-17T00:00:00.000Z"), requests[1]);
        eq("the result covers exactly the new window", [records.length, Math.min(...starts(records))],
           [7 * 24, day(11).getTime()]);

        records = await cache.load("/s", {start: day(12), end: day(14)});
        eq("narrowing is answered from memory", requests.length, 2);
        eq("with exactly the narrower window", records.length, 2 * 24);

        records = await cache.load("/s", {start: day(10), end: day(18)});
        eq("widening back to what was browsed is answered from memory too", requests.length, 2);
        eq("without repeating any record", new Set(starts(records)).size, records.length);

        await cache.load("/s", {start: day(1), end: day(3)});
        eq("a window apart from the held span is fetched whole", requests.length, 3);
        await cache.load("/s", {start: day(12), end: day(14)});
        eq("and replaces it, so going back fetches again", requests.length, 4);

        cache.reset();
        await cache.load("/s", {start: day(12), end: day(14)});
        eq("after a reset, everything is fetched again", requests.length, 5);
        """)


def test_cache_extends_a_window_touching_the_held_span(assert_js):
    """Stepping a selection on by exactly its own width keeps both spans."""
    assert_js(FAKE_API + """
        import { createChartDataCache } from "/js/chart-data-cache.js";
        const cache = createChartDataCache();
        await cache.load("/s", {start: day(10), end: day(17)});
        await cache.load("/s", {start: day(17), end: day(24)});
        await cache.load("/s", {start: day(10), end: day(24)});
        eq("the two adjacent weeks together need no third request", requests.length, 2);
        """)


def test_cache_forgets_records_past_their_age(assert_js):
    assert_js(FAKE_API + """
        import { createChartDataCache } from "/js/chart-data-cache.js";
        const cache = createChartDataCache({maxAgeMs: 30});
        await cache.load("/s", {start: day(10), end: day(17)});
        await cache.load("/s", {start: day(11), end: day(12)});
        eq("fresh records are reused", requests.length, 1);
        await new Promise((resolve) => setTimeout(resolve, 60));
        await cache.load("/s", {start: day(11), end: day(12)});
        eq("stale records are fetched afresh", requests.length, 2);
        check("for just the window asked", requests[1].includes("event_starts_after=2022-01-11"), requests[1]);
        """)


def test_cache_does_not_reuse_records_off_the_resampling_grid(assert_js):
    """A window offset from the held span by part of the resolution comes back on shifted timestamps."""
    assert_js(FAKE_API + """
        import { createChartDataCache } from "/js/chart-data-cache.js";
        const cache = createChartDataCache();
        await cache.load("/s", {start: day(10), end: day(17)});
        const halfHourLater = new Date(day(11).getTime() + HOUR / 2);
        await cache.load("/s", {start: halfHourLater, end: day(12)});
        eq("the shifted window is fetched rather than cut from what is held", requests.length, 2);
        """)
