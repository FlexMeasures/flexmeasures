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
