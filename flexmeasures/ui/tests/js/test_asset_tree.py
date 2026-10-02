"""Tests for flexmeasures/ui/static/js/asset-tree.js, the layout of the asset tree on the asset context page."""

# Builds an option for a list of assets, and helpers to find the drawn boxes in it.
TREE = """
import { buildAssetHierarchy, buildAssetTreeOption, wrapName, clampZoom, ZOOM_MIN, ZOOM_MAX } from "/js/asset-tree.js";
const layout = (assets, options = {}) => {
    const { assetMap, rootNodes } = buildAssetHierarchy(assets);
    return buildAssetTreeOption(rootNodes, assetMap, {width: 1000, viewportHeight: 600, ...options});
};
const boxes = (option) => option.series[0].data.filter((n) => n.symbol === "roundRect");
const box = (option, id) => boxes(option).find((n) => n.id === String(id));
const leaves = (parent, n) => Array.from({length: n}, (_, i) => ({id: 100 + i, name: `leaf ${i}`, parent}));
"""


def test_hierarchy(assert_js):
    assert_js("""
        import { buildAssetHierarchy } from "/js/asset-tree.js";
        const { assetMap, rootNodes } = buildAssetHierarchy([
            {id: 2, name: "battery", parent: 1},
            {id: 1, name: "site"},
            {id: 3, name: "orphan", parent: 99},
        ]);
        eq("assets without a parent in the list are roots", rootNodes.map((n) => n.name), ["site", "orphan"]);
        eq("children hang under their parent, whatever the order", assetMap[1].children.map((n) => n.name), ["battery"]);
        eq("every asset is kept", Object.keys(assetMap).length, 3);
        """)


def test_every_asset_is_drawn_and_connected(assert_js):
    assert_js(TREE + """
        const option = layout([
            {id: 1, name: "site"},
            {id: 2, name: "building", parent: 1},
            {id: 3, name: "battery", parent: 2},
            {id: 4, name: "solar", parent: 2},
            {id: "new", name: "Add asset", parent: 2},
        ]);
        eq("one box per asset", boxes(option).map((n) => n.id).sort(), ["1", "2", "3", "4", "new"]);
        const links = option.series[0].links;
        eq("the root has no connector of its own", links.filter((l) => l.target === "1").length, 0);
        eq("the building connects to the site", links.filter((l) => l.source === "1").length, 1);
        eq("the leaves connect to their parent through ports",
           links.filter((l) => l.target.startsWith("port-")).map((l) => [l.source, l.target]).sort(),
           [["2", "port-3"], ["2", "port-4"]]);
        eq("the action node is connected directly", links.filter((l) => l.target === "new").length, 1);
        check("children sit to the right of their parent",
              box(option, 3).x > box(option, 2).x && box(option, 2).x > box(option, 1).x);
        """)


def test_a_small_family_stays_on_one_row(assert_js):
    assert_js(TREE + """
        const option = layout([{id: 1, name: "site"}, ...leaves(1, 4)]);
        const ys = new Set([100, 101, 102, 103].map((id) => box(option, id).y));
        eq("four leaves share one row", ys.size, 1);
        eq("connectors arrive from above",
           option.series[0].links.map((l) => l.lineStyle.curveness), [0.18, 0.18, 0.18, 0.18]);
        """)


def test_a_wide_family_wraps_onto_two_balanced_rows_and_no_more(assert_js):
    assert_js(TREE + """
        const count = (option, n) => {
            const rows = {};
            for (let i = 0; i < n; i++) {
                const y = box(option, 100 + i).y;
                rows[y] = (rows[y] || 0) + 1;
            }
            return Object.entries(rows).sort((a, b) => a[0] - b[0]).map(([, k]) => k);
        };
        eq("too many leaves for one row are split over two, the top one at most one wider",
           count(layout([{id: 1, name: "site"}, ...leaves(1, 25)]), 25), [13, 12]);
        const wide = layout([{id: 1, name: "site"}, ...leaves(1, 40)]);
        eq("a wider family still keeps to two rows", count(wide, 40), [20, 20]);
        check("and shrinks its boxes to fit the width instead",
              boxes(wide).every((n) => n.x + n.symbolSize[0] / 2 <= 1000), JSON.stringify(boxes(wide).map((n) => n.x)));
        const bottomRow = wide.series[0].links.filter((l) => l.lineStyle && l.lineStyle.curveness < 0);
        eq("connectors to the bottom row arrive from below", bottomRow.length, 20);
        eq("even a huge family keeps to two rows", count(layout([{id: 1, name: "site"}, ...leaves(1, 80)]), 80), [40, 40]);
        """)


def test_the_current_asset_is_highlighted_by_id(assert_js):
    """Asset names are only unique among siblings, so a child may share its parent's name."""
    assert_js(TREE + """
        const option = layout([{id: 1, name: "Battery"}, {id: 2, name: "Battery", parent: 1}], {currentAssetId: 1});
        eq("only the current asset is gold", [box(option, 1).itemStyle.color, box(option, 2).itemStyle.color],
           ["#fcd34d", "#ffffff"]);
        check("and drawn slightly larger", box(option, 1).symbolSize[0] > box(option, 2).symbolSize[0]);
        """)


def test_only_the_action_node_looks_like_a_button(assert_js):
    """An asset may be called "Add asset" without turning into the button that adds one."""
    assert_js(TREE + """
        const option = layout([
            {id: 1, name: "site"},
            {id: 2, name: "Add asset", parent: 1},
            {id: "new", name: "Add asset", parent: 1},
        ]);
        eq("the real asset is drawn as an asset", box(option, 2).itemStyle.color, "#ffffff");
        eq("the action node is green", box(option, "new").itemStyle.color, "#10b981");
        """)


def test_labels_follow_the_zoom(assert_js):
    assert_js(TREE + """
        const assets = [{id: 1, name: "site", icon: "/icons/site.svg"}, ...leaves(1, 3)];
        const normal = box(layout(assets), 1).label;
        const zoomedIn = box(layout(assets, {zoomFactor: 2}), 1).label;
        const crowded = [{id: 1, name: "site"}, ...leaves(1, 40)];
        const zoomedOut = box(layout(crowded, {zoomFactor: ZOOM_MIN}), 1).label;
        check("zooming in enlarges the text", zoomedIn.fontSize > normal.fontSize, `${zoomedIn.fontSize} vs ${normal.fontSize}`);
        eq("zooming far out on small boxes hides the text", zoomedOut.show, false);
        eq("the icon is placed above the name", normal.formatter(), "{icon_1|}\\n{text|site}");
        eq("names are not read as ECharts templates", box(layout([{id: 1, name: "{b} and {c}"}]), 1).label.formatter(),
           "{text|{b} and {c}}");
        """)


def test_zoom_changes_the_series_but_not_the_canvas(assert_js):
    assert_js(TREE + """
        const assets = [{id: 1, name: "site"}, ...leaves(1, 3)];
        const pins = (option) => option.series[0].data.filter((n) => n.id.startsWith("__pin")).map((n) => [n.x, n.y]);
        eq("pins span the canvas", pins(layout(assets)), [[0, 0], [1000, 600]]);
        eq("whatever the zoom", pins(layout(assets, {zoomFactor: 2})), [[0, 0], [1000, 600]]);
        eq("the zoom is handed to the series", layout(assets, {zoomFactor: 2}).series[0].zoom, 2);
        eq("continuous zooming skips the animation", layout(assets, {animate: false}).series[0].animationDurationUpdate, 0);
        eq("a zoom is kept within bounds", [clampZoom(0.01), clampZoom(100), clampZoom(1.234)], [ZOOM_MIN, ZOOM_MAX, 1.23]);
        """)


def test_a_tall_tree_extends_the_canvas_downward(assert_js):
    assert_js(TREE + """
        const assets = [{id: 1, name: "site"}];
        for (let i = 2; i < 40; i++) assets.push({id: i, name: `building ${i}`, parent: 1}, {id: 1000 + i, name: "meter", parent: i});
        const option = layout(assets);
        const lowestPin = option.series[0].data.find((n) => n.id === "__pin1");
        check("the pin sits below the viewport, so the view zooms out to fit",
              lowestPin.y > 600, String(lowestPin.y));
        """)


def test_wrap_name(assert_js):
    assert_js("""
        import { wrapName } from "/js/asset-tree.js";
        eq("a short name fits on one line", wrapName("PV", 10, 3), "PV");
        eq("longer names break between words", wrapName("rooftop solar panels", 10, 3), "rooftop\\nsolar\\npanels");
        eq("words longer than a line are cut", wrapName("supercalifragilistic", 8, 3), "supercal\\nifragili\\nstic");
        eq("what does not fit ends in an ellipsis", wrapName("one two three four five", 5, 2), "one\\ntwo…");
        eq("names need not be strings", wrapName(42, 5, 1), "42");
        """)
