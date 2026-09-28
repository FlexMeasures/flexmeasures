"""Tests for flexmeasures/ui/static/js/chart-data-utils.js."""


def test_decompress_chart_data(assert_js):
    """The compressed response (>= FM v0.28) is expanded into the records the charts expect."""
    assert_js("""
        import { decompressChartData } from "/js/chart-data-utils.js";
        const response = {
            data: [{sid: 1, src: 9, ts: 1664661600000, val: 4.2, bh: 3600000, bt: 1664658000000}],
            sensors: {1: {name: "power", unit: "MW", event_resolution: 900, asset_id: 7}},
            sources: {9: {name: "forecaster", type: "forecaster"}},
        };
        const rows = decompressChartData(response);
        eq("one belief in, one record out", rows.length, 1);
        eq("the event start is carried over", rows[0].event_start, 1664661600000);
        eq("the value is carried over", rows[0].event_value, 4.2);
        eq("the sensor is reconstructed", rows[0].sensor.id, 1);
        eq("the sensor's resolution is carried over", rows[0].sensor.event_resolution, 900);
        eq("the source is reconstructed", rows[0].source.name, "forecaster");
        """)


def test_decompress_passes_through_the_old_format(assert_js):
    assert_js("""
        import { decompressChartData } from "/js/chart-data-utils.js";
        const old = [{event_start: 1, event_value: 2}];
        eq("data already in the old format is returned unchanged", decompressChartData(old), old);
        """)


def test_seconds_valued_sensors_become_dates(assert_js):
    """A sensor recording seconds is charted as a moment in time."""
    assert_js("""
        import { decompressChartData } from "/js/chart-data-utils.js";
        const rows = decompressChartData({
            data: [{sid: 1, src: 9, ts: 0, val: 60}],
            sensors: {1: {name: "arrival", unit: "s"}},
            sources: {9: {name: "scheduler"}},
        });
        check("a seconds value is converted to a Date", rows[0].event_value instanceof Date,
              String(rows[0].event_value));
        eq("60 seconds is one minute past the epoch", rows[0].event_value.getTime(), 60000);
        """)


# Captures the toasts a function shows, rather than rendering them.
CAPTURE_TOASTS = """
const toasts = [];
window.showToast = (message, type) => toasts.push({message, type});
"""


def test_dst_transitions_are_pointed_out(assert_js):
    assert_js(
        CAPTURE_TOASTS + """
        import { checkDSTTransitions } from "/js/chart-data-utils.js";
        checkDSTTransitions(new Date(2022, 5, 1), new Date(2022, 5, 8));
        eq("a week in summer says nothing", toasts.length, 0);
        checkDSTTransitions(new Date(2022, 2, 24), new Date(2022, 2, 30));
        check("a week around the spring transition mentions one",
              toasts.length === 1 && toasts[0].message.includes("a daylight saving time (DST) transition"),
              JSON.stringify(toasts));
        checkDSTTransitions(new Date(2022, 0, 1), new Date(2022, 11, 31));
        check("a year mentions both", toasts.length === 2 && toasts[1].message.includes(" 2 daylight saving"),
              JSON.stringify(toasts));
        """,
        timezone="Europe/Amsterdam",
    )


def test_source_masking_is_pointed_out_on_heatmaps_only(assert_js):
    """The daily heatmap shows only the most prevalent source."""
    assert_js(CAPTURE_TOASTS + """
        import { checkSourceMasking } from "/js/chart-data-utils.js";
        const twoSources = [{source: {id: 1}}, {source: {id: 2}}];
        checkSourceMasking(twoSources, "bar_chart");
        eq("other chart types show every source, so say nothing", toasts.length, 0);
        checkSourceMasking([{source: {id: 1}}, {source: {id: 1}}], "daily_heatmap");
        eq("a single source hides nothing", toasts.length, 0);
        checkSourceMasking(twoSources, "daily_heatmap");
        eq("several sources on a heatmap are pointed out", toasts.length, 1);
        """)


def test_strict_y_axis_ranges(assert_js):
    """Data outside a strict y-axis range is drawn clamped, so the viewer is told once."""
    assert_js(CAPTURE_TOASTS + """
        import { checkStrictYAxisRanges } from "/js/chart-data-utils.js";
        const sensorsToShow = [
            {title: "Prices", plots: [{sensor: 1}], "y-axis": {min: 0, max: 100}},
            {title: "Loose", plots: [{sensor: 2}], "y-axis": [0, 10]},
            {title: "Several", plots: [{sensors: [3, 4]}], "y-axis": {min: -5, max: 5}},
        ];
        const datum = (sensor, value) => ({sensor: {id: sensor}, event_value: value});

        checkStrictYAxisRanges([datum(1, 50), datum(2, 500), datum(3, 0)], sensorsToShow);
        eq("values inside the range, or on a non-strict axis, say nothing", toasts.length, 0);

        checkStrictYAxisRanges([datum(1, 150)], sensorsToShow);
        eq("a value above the range is pointed out", toasts.map((t) => t.type), ["warning"]);
        check("naming the graph and its range", toasts[0].message.includes("'Prices'") && toasts[0].message.includes("(0 to 100)"),
              toasts[0].message);

        checkStrictYAxisRanges([datum(1, 150)], sensorsToShow);
        eq("the same situation is not pointed out twice", toasts.length, 1);

        checkStrictYAxisRanges([datum(4, -6)], sensorsToShow);
        check("sensors listed together count too", toasts.length === 2 && toasts[1].message.includes("'Several'"),
              JSON.stringify(toasts));

        checkStrictYAxisRanges([], sensorsToShow);
        checkStrictYAxisRanges([datum(4, -6)], sensorsToShow);
        eq("once everything was back in range, a new excursion is pointed out again", toasts.length, 3);

        checkStrictYAxisRanges([datum(1, 150)], undefined);
        eq("without graphs to check, nothing is said", toasts.length, 3);
        """)


def test_snap_range_to_events_rounds_out_to_whole_events(assert_js):
    """A range drawn across 15-minute events covers the whole events it touches (the case reported in PR #2570)."""
    assert_js("""
        import { snapRangeToEvents } from "/js/chart-data-utils.js";
        const quarter = 15 * 60 * 1000;
        const anchor = Date.parse("2030-01-15T00:00:00Z");
        const snapped = snapRangeToEvents(
            {start: new Date("2030-01-15T14:21:37Z"), end: new Date("2030-01-15T14:51:02Z")}, quarter, anchor
        );
        eq("the start is rounded down", snapped.start.toISOString(), "2030-01-15T14:15:00.000Z");
        eq("the end is rounded up", snapped.end.toISOString(), "2030-01-15T15:00:00.000Z");

        const late = snapRangeToEvents(
            {start: new Date("2030-01-15T14:29:00Z"), end: new Date("2030-01-15T14:31:00Z")}, quarter, anchor
        );
        eq("a start near the next event is still rounded down", late.start.toISOString(), "2030-01-15T14:15:00.000Z");
        eq("an end just past an event is still rounded up", late.end.toISOString(), "2030-01-15T14:45:00.000Z");

        const aligned = snapRangeToEvents(
            {start: new Date("2030-01-15T14:15:00Z"), end: new Date("2030-01-15T15:00:00Z")}, quarter, anchor
        );
        eq("an aligned range is kept", [aligned.start.toISOString(), aligned.end.toISOString()],
           ["2030-01-15T14:15:00.000Z", "2030-01-15T15:00:00.000Z"]);

        const click = snapRangeToEvents(
            {start: new Date("2030-01-15T14:20:00Z"), end: new Date("2030-01-15T14:20:00Z")}, quarter, anchor
        );
        eq("an empty range becomes the event it lies in", [click.start.toISOString(), click.end.toISOString()],
           ["2030-01-15T14:15:00.000Z", "2030-01-15T14:30:00.000Z"]);

        const instant = snapRangeToEvents(
            {start: new Date("2030-01-15T14:21:37Z"), end: new Date("2030-01-15T14:51:02Z")}, 0, anchor
        );
        eq("an instantaneous sensor keeps the range", instant.end.toISOString(), "2030-01-15T14:51:02.000Z");
        """)


def test_snap_range_to_daily_events_across_dst(assert_js):
    """Daily events keep their local midnights across the spring DST transition."""
    assert_js(
        """
        import { snapRangeToEvents } from "/js/chart-data-utils.js";
        const day = 24 * 60 * 60 * 1000;
        const anchor = Date.parse("2030-03-01T00:00:00+01:00");
        const snapped = snapRangeToEvents(
            {start: new Date("2030-03-31T10:00:00+02:00"), end: new Date("2030-04-01T05:00:00+02:00")}, day, anchor
        );
        eq("the start is the local midnight before the transition", snapped.start.toISOString(), "2030-03-30T23:00:00.000Z");
        eq("the end is a local midnight after the transition", snapped.end.toISOString(), "2030-04-01T22:00:00.000Z");
        """,
        timezone="Europe/Amsterdam",
    )


def test_snap_selection_rounds_instants_and_instantaneous_ranges(assert_js):
    """An instant, or a range on an instantaneous sensor, is rounded to the nearest minute, and may become an instant."""
    assert_js("""
        import { snapSelection } from "/js/chart-data-utils.js";
        const at = (s) => new Date(`2030-01-15T${s}Z`);
        const iso = (r) => [r.start.toISOString().slice(11, 19), r.end.toISOString().slice(11, 19)];
        eq("a range within one minute becomes a minute",
           iso(snapSelection({start: at("09:03:25"), end: at("09:03:51")}, 0, 0)), ["09:03:00", "09:04:00"]);
        eq("a range around a whole minute becomes an instant",
           iso(snapSelection({start: at("09:02:59"), end: at("09:03:02")}, 0, 0)), ["09:03:00", "09:03:00"]);
        eq("an instant on a sensor with a resolution is rounded to the nearest minute",
           iso(snapSelection({start: at("09:07:31"), end: at("09:07:31")}, 900000, 0)), ["09:08:00", "09:08:00"]);
        eq("a range on a sensor with a resolution covers whole events",
           iso(snapSelection({start: at("09:07:31"), end: at("09:20:00")}, 900000, 0)), ["09:00:00", "09:30:00"]);
        eq("a finer step keeps seconds",
           iso(snapSelection({start: at("09:03:25.4"), end: at("09:03:51.6")}, 0, 0, 1000)), ["09:03:25", "09:03:52"]);
        """)
