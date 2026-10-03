"""Checks on the cards the graph dialogue is built from."""

from __future__ import annotations

STUB_API = """
localStorage.clear();
// Sensor 1 is there, sensor 404 is not: a graph can refer to a sensor deleted since it was configured.
window.fetch = async (url) => {
    if (url.includes("/sensors/404")) {
        return {ok: false, status: 404, json: async () => ({message: "Sensor not found"})};
    }
    if (url.includes("/sensors/")) {
        return {ok: true, json: async () => ({id: 1, name: "Power", unit: "MW", generic_asset_id: 2})};
    }
    if (url.includes("/assets/")) {
        return {ok: true, json: async () => ({id: 2, name: "Battery", account_id: 3})};
    }
    return {ok: true, json: async () => ({id: 3, name: "Acme"})};
};
"""


def test_a_sensor_card_says_which_sensor_it_shows(assert_js):
    assert_js(STUB_API + """
        import { renderSensorCard } from "/js/components.js";

        const card = await renderSensorCard(1, 0);
        eq("the sensor's unit comes back with the card", card.unit, "MW");
        eq("and the sensor is not reported as gone", card.missing, false);
        const text = card.element.textContent;
        check("the card names the sensor", text.includes("Power"), text);
        check("and its asset", text.includes("Battery"), text);
        check("and its account", text.includes("Acme"), text);
        localStorage.clear();
        """)


def test_a_sensor_card_for_a_sensor_which_is_gone_stays_removable(assert_js):
    """A graph can refer to a deleted sensor, and the dialogue has to let the user take it out."""
    assert_js(STUB_API + """
        import { renderSensorCard } from "/js/components.js";
        import { missingSensorLabel } from "/js/ui-utils.js";

        const removals = [];
        const card = await renderSensorCard(404, 7, (...args) => removals.push(args), 2, 1);
        eq("the sensor is reported as gone", card.missing, true);
        eq("so there is no unit to compare", card.unit, null);
        const text = card.element.textContent;
        check("the card says the sensor is gone", text.includes(missingSensorLabel(404)), text);

        const closeIcon = card.element.querySelector("i.fa-times");
        check("and offers to remove the reference", closeIcon !== null, card.element.innerHTML);
        closeIcon.click();
        eq("which takes the sensor out of its plot", removals, [[2, 7, 1]]);
        localStorage.clear();
        """)


def test_a_sensor_which_is_gone_does_not_make_a_graph_mixed_unit(assert_js):
    """A reference without a sensor has no unit, so it cannot disagree with the units that are there."""
    assert_js(STUB_API + """
        import { renderSensorsList } from "/js/components.js";

        const list = await renderSensorsList([1, 404], 0);
        eq("only the sensors that are there are compared", list.uniqueUnits, ["MW"]);
        eq("and the dangling reference is counted", list.missingCount, 1);

        const intact = await renderSensorsList([1, 1], 0);
        eq("a list of sensors that are all there counts none", intact.missingCount, 0);
        localStorage.clear();
        """)
