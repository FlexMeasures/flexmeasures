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
