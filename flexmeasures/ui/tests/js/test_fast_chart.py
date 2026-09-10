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
    assert_js(
        SIDE_LEGEND_CHART
        + """
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
        """
    )


def test_export_legend_uses_the_full_band_beside_its_subplot(assert_js):
    """One subplot means the legend may run past the plot's height, into a single column."""
    assert_js(
        SIDE_LEGEND_CHART
        + """
        import { buildExportOption } from "/js/fast-chart.js";
        const exported = buildExportOption(chart(13), 1200, 400);
        const legend = exported.option.legend[0];
        eq("the legend starts level with its subplot", legend.top, 66);
        check("the legend may use the height below the plot too", legend.height > 150,
              `height ${legend.height}`);
        check("13 entries fit in one column", legend.height >= 13 * 25, `height ${legend.height}`);
        """
    )


def test_export_legend_shows_names_in_full(assert_js):
    """An image has no hover to reveal a truncated name, so the export shows them all."""
    assert_js(
        SIDE_LEGEND_CHART
        + """
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
        """
    )


def test_export_leaves_a_legend_below_the_plots_alone(assert_js):
    """With legends below (the "keep legends below graphs" setting), the chart already fits them."""
    assert_js(
        """
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
        """
    )


def test_export_hides_the_toolbox(assert_js):
    """The zoom/pan/save buttons are chrome, not part of the picture."""
    assert_js(
        SIDE_LEGEND_CHART
        + """
        import { buildExportOption } from "/js/fast-chart.js";
        const exported = buildExportOption(chart(3), 1200, 400);
        eq("the toolbox is hidden", exported.option.toolbox.show, false);
        eq("the background is opaque, so the image is not transparent",
           exported.option.backgroundColor, "#fff");
        eq("progressive rendering is off, so every series is drawn in one pass",
           exported.option.series[0].progressive, 0);
        """
    )
