"""Tests for flexmeasures/ui/static/js/fast-chart.js."""


def test_bar_interval_of_a_daily_sensor_with_one_data_point(assert_js):
    """A bar stands for one event resolution, also when the series holds a single point (issue #2454).

    ECharts would otherwise derive the width from the spacing between points, of which a single point has none.
    """
    assert_js("""
        import { barIntervalMs } from "/js/fast-chart.js";
        const daily = {eventResolutionSec: 86400, eventStarts: [Date.UTC(2030, 0, 15)]};
        eq("one point of a daily sensor still spans a day", barIntervalMs(daily), 86400000);
        const quarterly = {eventResolutionSec: 900, eventStarts: [Date.UTC(2030, 0, 15)]};
        eq("one point of a 15-minute sensor spans 15 minutes", barIntervalMs(quarterly), 900000);
        """)


def test_bar_interval_falls_back_to_the_event_spacing(assert_js):
    """Instantaneous sensors and legacy data without a resolution fall back to the spacing between events."""
    assert_js("""
        import { barIntervalMs } from "/js/fast-chart.js";
        const day = 24 * 3600 * 1000;
        const starts = [Date.UTC(2030, 0, 14), Date.UTC(2030, 0, 15), Date.UTC(2030, 0, 16)];
        eq("an instantaneous sensor falls back to the spacing", barIntervalMs({eventResolutionSec: 0, eventStarts: starts}), day);
        eq("legacy data without a resolution falls back too", barIntervalMs({eventResolutionSec: null, eventStarts: starts}), day);
        eq("a single point without a resolution falls back to an hour", barIntervalMs({eventResolutionSec: 0, eventStarts: [0]}), 3600000);
        """)


def test_bar_width_covers_exactly_one_interval(assert_js):
    """The width is picked so that the bar covers one interval on the axis ECharts ends up drawing.

    ECharts widens a bar chart's axis by the width of its widest bar, so the width has to account for that widening.
    """
    assert_js("""
        import { barWidthPx } from "/js/fast-chart.js";
        const day = 24 * 3600 * 1000;
        // The sensor page from issue #2454: a daily sensor shown over three days, in a 900 px wide grid.
        const width = barWidthPx(day, 3 * day, 900);
        eq("a day of a three-day window is a quarter of the widened axis", width, 225);
        // ECharts widens the 3-day axis by that bar width, to 4 days, on which 225 px is exactly one day.
        eq("the bar then covers exactly one day", (width * 4 * day) / 900, day);
        eq("a 15-minute bar of a two-day window is a sliver", +barWidthPx(900000, 2 * day, 900).toFixed(2), 4.66);
        """)


def test_bar_width_stays_within_bounds(assert_js):
    """Degenerate inputs yield no width at all, and a bar never shrinks away or exceeds the grid."""
    assert_js("""
        import { barWidthPx } from "/js/fast-chart.js";
        const day = 24 * 3600 * 1000;
        eq("an unknown interval yields no width", barWidthPx(0, 3 * day, 900), null);
        eq("an empty window yields no width", barWidthPx(day, 0, 900), null);
        eq("a collapsed grid yields no width", barWidthPx(day, 3 * day, 0), null);
        check("a bar much narrower than a pixel still shows", barWidthPx(60000, 365 * day, 900) === 1);
        check("a bar wider than the window stays inside the grid", barWidthPx(day, 60000, 900) < 900);
        """)


def test_a_bar_reports_the_event_it_covers(assert_js):
    """A bar is drawn over the resolution following its event start, and its tooltip reports that start.

    The bar is plotted half a resolution late to get there, so the lookup takes that offset back out.
    Without that, a bar whose neighbour sits closer than half a resolution — irregularly spaced data, such as a sensor whose resolution changed — would report its neighbour's event.
    """
    assert_js("""
        import { nearestRealPoint } from "/js/fast-chart.js";
        const day = 24 * 3600 * 1000;
        const midnight = Date.UTC(2030, 0, 15);
        const six = midnight + 6 * 3600 * 1000;
        const meta = {points: [[midnight, 122.4294, 0], [six, 90, 0]], xOffsetMs: day / 2};
        eq("the first bar reports its own event", nearestRealPoint(meta, [midnight + day / 2, 122.4294])[0], midnight);
        eq("the second bar reports its own event", nearestRealPoint(meta, [six + day / 2, 90])[0], six);
        const line = {points: [[midnight, 122.4294, 0]]};
        eq("a series drawn on its event starts is looked up as it is", nearestRealPoint(line, [midnight, 122.4294])[0], midnight);
        """)
