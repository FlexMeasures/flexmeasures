"""Tests for flexmeasures/ui/static/js/fast-chart.js."""

# A chart as fast-chart.js lays one out: a 1200x400 canvas with one subplot and,
# beside it, a paginated legend of 13 sensors (the case reported in issue #2513).
SIDE_LEGEND_CHART = """
    const chart = (entries) => {
        const labels = [];
        for (let i = 0; i < entries; i++) {
            labels.push("consumption tariff (Supplier " + i + ", low voltage)");
        }
        return {
            grid: [{top: 66, height: 150, left: 70, right: 260}],
            legend: [{
                data: labels,
                type: "scroll",
                orient: "vertical",
                right: 8,
                top: 66,
                height: 150,
                textStyle: {fontSize: 16, width: 190, overflow: "truncate"},
            }],
            series: [{type: "line", data: []}],
            toolbox: [{feature: {}}],
        };
    };
    const plotRight = (exported) => exported.width - exported.option.grid[0].right;
"""


def test_export_legend_clears_the_plot(assert_js):
    """Every legend entry shows in an export, to the right of the plot (issue #2513)."""
    assert_js(SIDE_LEGEND_CHART + """
        import { buildExportOption } from "/js/fast-chart.js";
        const exported = buildExportOption(chart(13), 1200, 400);
        const legend = exported.option.legend[0];
        eq("the paginated legend becomes a plain one, so no entry is hidden", legend.type, "plain");
        check("the legend starts to the right of the plot", legend.left >= plotRight(exported),
              `legend at ${legend.left}, plot ends at ${plotRight(exported)}`);
        check("the canvas grows to make room for the legend", exported.width > 1200,
              `width ${exported.width}`);
        eq("the plot keeps its width", plotRight(exported) - exported.option.grid[0].left, 1200 - 260 - 70);
        eq("the exported chart keeps its height", exported.height, 400);
        """)


def test_export_legend_uses_the_full_band_beside_its_subplot(assert_js):
    """One subplot means the legend may run past the plot's height, into a single column."""
    assert_js(SIDE_LEGEND_CHART + """
        import { buildExportOption } from "/js/fast-chart.js";
        const exported = buildExportOption(chart(13), 1200, 400);
        const legend = exported.option.legend[0];
        eq("the legend starts level with its subplot", legend.top, 66);
        check("the legend may use the height below the plot too", legend.height > 150,
              `height ${legend.height}`);
        check("13 entries fit in one column", legend.height >= 13 * 25, `height ${legend.height}`);
        """)


def test_export_legend_shows_names_in_full(assert_js):
    """An image has no hover to reveal a truncated name, so the export shows them all."""
    assert_js(SIDE_LEGEND_CHART + """
        import { buildExportOption } from "/js/fast-chart.js";
        const exported = buildExportOption(chart(13), 1200, 400);
        eq("labels are no longer truncated", exported.option.legend[0].textStyle.overflow, "none");

        // ... except for a name so long that showing it would blow up the image.
        const long = chart(2);
        long.legend[0].data = ["x".repeat(400), "short"];
        const wide = buildExportOption(long, 1200, 400);
        eq("a very long name stays truncated", wide.option.legend[0].textStyle.overflow, "truncate");
        check("the exported image stays a sane width", wide.width < 1200 + 500,
              `width ${wide.width}`);
        """)


def test_export_leaves_a_legend_below_the_plots_alone(assert_js):
    """With legends below (the "keep legends below graphs" setting), the chart already fits them."""
    assert_js("""
        import { buildExportOption } from "/js/fast-chart.js";
        const option = {
            grid: [{top: 66, height: 150, left: 70, right: 30}],
            legend: [{data: ["a", "b"], type: "plain", orient: "vertical", left: 70, top: 300}],
            series: [{type: "line", data: []}],
        };
        const exported = buildExportOption(option, 1200, 500);
        eq("the canvas is not widened", exported.width, 1200);
        eq("the legend stays where it is", exported.option.legend[0].left, 70);
        eq("the plot keeps its margins", exported.option.grid[0].right, 30);
        """)


def test_export_hides_the_toolbox(assert_js):
    """The zoom/pan/save buttons are chrome, not part of the picture."""
    assert_js(SIDE_LEGEND_CHART + """
        import { buildExportOption } from "/js/fast-chart.js";
        const exported = buildExportOption(chart(3), 1200, 400);
        eq("the toolbox is hidden", exported.option.toolbox.show, false);
        eq("the background is opaque, so the image is not transparent",
           exported.option.backgroundColor, "#fff");
        eq("progressive rendering is off, so every series is drawn in one pass",
           exported.option.series[0].progressive, 0);
        """)


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
