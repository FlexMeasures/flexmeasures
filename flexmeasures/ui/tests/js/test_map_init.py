"""Tests for the tree layout in flexmeasures/ui/static/js/map-init.js.

Like flexmeasures.js, map-init.js is a classic script whose functions become globals.
Leaflet is only needed to turn the positions into points, so a stand-in suffices.
"""

LOAD_MAP_INIT = """
window.L = {point: (p) => p};
await new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/js/map-init.js";
    script.onload = resolve;
    script.onerror = () => reject(new Error("could not load map-init.js"));
    document.head.append(script);
});
const marker = (id, parentId) => ({options: {id, parentId}});
"""


def test_a_tree_is_centered_on_the_cluster(assert_js):
    assert_js(LOAD_MAP_INIT + """
        const positions = computeCenteredTreeLayout(
            [marker(1, null), marker(2, 1), marker(3, 1)], {x: 100, y: 200});
        eq("the parent sits above its children, midway", positions[0], {x: 100, y: 150});
        eq("the children sit side by side, one level down", [positions[1], positions[2]], [{x: 75, y: 250}, {x: 125, y: 250}]);
        """)


def test_trees_sit_side_by_side(assert_js):
    assert_js(LOAD_MAP_INIT + """
        const positions = computeCenteredTreeLayout(
            [marker(1, null), marker(2, 1), marker(3, 1), marker(4, null), marker(5, 4), marker(6, 4)], {x: 0, y: 0});
        const xs = positions.map((p) => p.x);
        check("the second tree lies entirely to the right of the first",
              Math.max(...xs.slice(0, 3)) < Math.min(...xs.slice(3)), JSON.stringify(positions));
        eq("the forest is centered", Math.min(...xs) + Math.max(...xs), 0);
        eq("both trees keep their shape", [xs[2] - xs[1], xs[5] - xs[4]], [50, 50]);
        """)


def test_markers_whose_parent_has_no_marker_are_still_grouped(assert_js):
    """A parent without a location has no marker, but its children still form one family."""
    assert_js(LOAD_MAP_INIT + """
        const positions = computeCenteredTreeLayout([marker(2, 9), marker(3, 9)], {x: 0, y: 0});
        eq("siblings are placed side by side", positions, [{x: -25, y: 50}, {x: 25, y: 50}]);
        """)


def test_custom_spacing(assert_js):
    assert_js(LOAD_MAP_INIT + """
        const positions = computeCenteredTreeLayout(
            [marker(1, null), marker(2, 1), marker(3, 1)], {x: 0, y: 0}, 10, 20);
        eq("the spacing is honoured", positions, [{x: 0, y: -10}, {x: -5, y: 10}, {x: 5, y: 10}]);
        """)
