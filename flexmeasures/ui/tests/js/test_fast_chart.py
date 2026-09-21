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


def test_belief_tooltip_compacts_and_expands_without_new_data(assert_js):
    """Compact belief tooltips keep essentials; the switch reveals provenance."""
    assert_js("""
        import { singlePointTooltip } from "/js/fast-chart.js";

        const meta = {
            sensorDescription: "Grid power (ID: 7)",
            sensorType: "power",
            unit: "kW",
            source: {
                id: 3,
                name: "Weather model",
                display_type: "forecaster",
                model: "LinearRegression",
                version: "2.0",
            },
        };
        const value = [Date.parse("2026-09-21T10:00:00Z"), 12.5, 3600000];
        const rowCount = (html) => (html.match(/<tr>/g) || []).length;

        const sensorCompact = singlePointTooltip(meta, value, {
            showSensor: false,
            fullBeliefInfo: false,
        });
        eq("sensor compact mode has value and time", rowCount(sensorCompact), 2);
        check("compact mode includes the exact value", sensorCompact.includes("12.5 kW"));
        check("compact mode includes time", sensorCompact.includes("Time and date"));
        check("sensor compact mode omits the redundant sensor", !sensorCompact.includes("Sensor"));
        check("compact mode omits provenance", !sensorCompact.includes("Horizon"));

        const assetCompact = singlePointTooltip(meta, value, {
            showSensor: true,
            fullBeliefInfo: false,
        });
        eq("asset compact mode adds the sensor", rowCount(assetCompact), 3);
        check("asset compact mode identifies the sensor", assetCompact.includes("Grid power (ID: 7)"));

        const assetFull = singlePointTooltip(meta, value, {
            showSensor: true,
            fullBeliefInfo: true,
        });
        eq("full asset mode restores all eight fields", rowCount(assetFull), 8);
        ["Horizon", "Source", "Type", "Model", "Version"].forEach((field) => {
            check(`full mode includes ${field}`, assetFull.includes(field));
        });

        const sensorFull = singlePointTooltip(meta, value, {
            showSensor: false,
            fullBeliefInfo: true,
        });
        eq("full sensor mode has seven fields", rowCount(sensorFull), 7);
        check("sensor identity stays omitted on its own page", !sensorFull.includes("Sensor"));
        """)


def test_charge_point_sessions_keep_their_own_tooltip(assert_js):
    """The belief preference does not break purpose-built session tooltips."""
    assert_js("""
        const originalMatchMedia = window.matchMedia;
        window.matchMedia = () => ({matches: true});
        const { buildChargePointSessionsOption } = await import("/js/fast-chart.js?sessions-touch");
        window.matchMedia = originalMatchMedia;

        const container = document.createElement("div");
        container.id = "sessions-chart";
        document.body.appendChild(container);
        const eventStart = Date.parse("2026-09-21T10:00:00Z");
        const sensor = (name) => ({
            id: name === "arrival" ? 1 : 2,
            name,
            unit: "s",
            asset_id: 4,
            asset_description: "Charger 4",
        });
        const option = buildChargePointSessionsOption("sessions-chart", [
            {sensor: sensor("arrival"), event_start: eventStart, event_value: eventStart},
            {sensor: sensor("departure"), event_start: eventStart, event_value: eventStart + 3600000},
        ], {groupSpec: [], datasetName: "sessions", isSensorPage: false});

        check("the session chart renders", option.series.length >= 2);
        const visibleSession = option.series.find((series) => series.tooltip && series.tooltip.formatter);
        const tooltip = visibleSession.tooltip.formatter();
        check("session start stays visible", tooltip.includes("Arrival"));
        check("session end stays visible", tooltip.includes("Departure"));
        check("session asset stays visible", tooltip.includes("Charger 4"));
        """)


def test_annotation_hover_survives_canvas_exit_and_pin(assert_js):
    """Pinned text stays stable while hovered text occupies a separate row."""
    assert_js("""
        import { wireAnnotationHover } from "/js/fast-chart.js";

        const canvasHandlers = {};
        const chartHandlers = {};
        const patches = [];
        const container = document.createElement("div");
        const canvas = document.createElement("canvas");
        const tooltip = document.createElement("div");
        container.appendChild(canvas);
        container.appendChild(tooltip);
        document.body.appendChild(container);
        container.getBoundingClientRect = () => ({left: 20, top: 30});
        canvas.getBoundingClientRect = () => ({left: 35, top: 50});
        const move = (target, x) => target.dispatchEvent(
            new MouseEvent("mousemove", {bubbles: true, clientX: x + 35, clientY: 60})
        );
        const zr = {
            on: (name, handler) => { canvasHandlers[name] = handler; },
            off: (name) => { delete canvasHandlers[name]; },
        };
        const chart = {
            getZr: () => zr,
            getDom: () => container,
            containPixel: (_grid, [x, y]) => x >= 0 && x < 20 && y >= 0 && y < 100,
            convertFromPixel: (_axis, x) => x,
            convertToPixel: (_axis, x) => x,
            setOption: (patch) => patches.push(patch),
            on: (name, handler) => { chartHandlers[name] = handler; },
            off: (name) => { delete chartHandlers[name]; },
        };
        const instance = {
            chart,
            replayTime: null,
            _annotCtx: {
                annotations: [
                    {start: 0, end: 10, label: "Pinned\\nnote", type: "label"},
                    {start: 10, end: 20, label: "Hovered note", type: "label"},
                ],
                grids: [{
                    seriesIndex: 0,
                    toleranceMs: 1,
                    labelTop: 100,
                    labelLeft: 0,
                    labelRight: 200,
                }],
            },
        };
        const shown = (label) => label.style.display === "inline-block";

        wireAnnotationHover(instance);
        const pinLabel = container.querySelector('[data-annotation-label="pin"]');
        const hoverLabel = container.querySelector('[data-annotation-label="hover"]');
        move(canvas, 5);
        check("hover shows the annotation", shown(hoverLabel));
        eq("multiline content stays in one stable row", hoverLabel.textContent, "Pinned · note");
        eq("the full multiline content remains available", hoverLabel.title, "Pinned\\nnote");
        eq("the label accounts for the padded canvas origin", hoverLabel.style.left, "15px");
        eq("the label accounts for the canvas's vertical offset", hoverLabel.style.top, "120px");
        check("canvas annotation labels stay disabled",
              !patches.at(-1).series[0].markArea.data[0][0].label.show);
        const patchCount = patches.length;
        move(canvas, 6);
        eq("movement within one annotation does not redraw it", patches.length, patchCount);
        move(tooltip, 6);
        check("moving across the HTML tooltip keeps the annotation", shown(hoverLabel));

        container.dispatchEvent(new MouseEvent("mouseleave"));
        check("leaving the chart clears an unpinned annotation", !shown(hoverLabel));

        canvasHandlers.click({offsetX: 5, offsetY: 10});
        container.dispatchEvent(new MouseEvent("mouseleave"));
        check("the annotation stays visible after a click and pointer exit", shown(pinLabel));
        eq("the pin has the clicked content", pinLabel.textContent, "Pinned · note");
        const pinnedPosition = pinLabel.style.cssText;

        move(canvas, 15);
        check("the pin remains visible while another annotation is hovered", shown(pinLabel));
        eq("hover does not rewrite or move the pinned label", pinLabel.style.cssText, pinnedPosition);
        eq("the second annotation is also visible", hoverLabel.textContent, "Hovered note");
        check("the two labels occupy separate rows", pinLabel.style.top !== hoverLabel.style.top,
              `${pinLabel.style.top} and ${hoverLabel.style.top}`);
        chartHandlers.datazoom();
        eq("zoom keeps the pin in its stable row", pinLabel.style.cssText, pinnedPosition);

        canvasHandlers.click({offsetX: 150, offsetY: 150});
        check("clicking outside releases the pin", !shown(pinLabel));

        wireAnnotationHover(instance);
        check("rewiring removes the old label nodes", !pinLabel.isConnected && !hoverLabel.isConnected);
        eq("rewiring creates exactly one stable pair", container.querySelectorAll(
            "[data-annotation-label]"
        ).length, 2);
        """)
