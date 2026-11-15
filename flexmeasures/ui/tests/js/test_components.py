"""Checks on the cards the graph dialogue is built from."""

from __future__ import annotations

STUB_API = """
localStorage.clear();
// Sensor 1 is there, sensor 404 is not: a graph can refer to a sensor deleted since it was configured.
// Sensor 500 may well be there, but the API failed to say so.
// Asset 9 is there, and its flex-context refers to sensor 404.
window.fetch = async (url) => {
    if (url.includes("/sensors/404")) {
        return {ok: false, status: 404, json: async () => ({message: "Sensor not found"})};
    }
    if (url.includes("/sensors/500")) {
        return {ok: false, status: 500, json: async () => ({message: "Internal error"})};
    }
    if (url.includes("/sensors/")) {
        return {ok: true, json: async () => ({id: 1, name: "Power", unit: "MW", generic_asset_id: 2})};
    }
    if (url.includes("/assets/9")) {
        return {ok: true, json: async () => ({
            id: 9, name: "Site", account_id: 3, flex_context: {"consumption-price": {sensor: 404}},
        })};
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
        check("the card says the sensor is gone", text.includes(missingSensorLabel(404, true)), text);

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


def test_a_sensor_card_does_not_call_a_sensor_gone_when_the_api_failed(assert_js):
    """Only a 404 means a sensor is gone; a server error says no more than that it could not be loaded."""
    assert_js(STUB_API + """
        import { renderSensorCard, renderSensorsList } from "/js/components.js";
        import { missingSensorLabel } from "/js/ui-utils.js";

        const card = await renderSensorCard(500, 0);
        eq("the sensor is not reported as gone", card.missing, false);
        eq("though there is no unit to compare", card.unit, null);
        const text = card.element.textContent;
        check("the card says it could not be loaded", text.includes(missingSensorLabel(500, false)), text);
        check("and not that it was deleted", !text.includes("deleted"), text);

        const list = await renderSensorsList([1, 500], 0);
        eq("so it is not counted among the references to remove", list.missingCount, 0);
        eq("and its unknown unit is not compared", list.uniqueUnits, ["MW"]);
        localStorage.clear();
        """)


def test_an_asset_plot_reports_the_sensor_its_flex_config_refers_to_as_gone(assert_js):
    """An asset plot can render a sensor its asset's flex config refers to, which can be gone too."""
    assert_js(STUB_API + """
        import { renderAssetPlotCard } from "/js/components.js";
        import { missingSensorLabel } from "/js/ui-utils.js";

        // The sensor was remembered while it was there; it has been deleted since.
        localStorage.setItem("sensor_404", JSON.stringify({id: 404, name: "Old price", unit: "EUR/MWh", generic_asset_id: 2}));

        const card = await renderAssetPlotCard({asset: 9, "flex-context": "consumption-price"}, () => {}, 0, 0);
        eq("the sensor is reported as gone, for the dialogue to count", card.missing, true);
        const text = card.element.textContent;
        check("rather than shown as it was when last looked up", !text.includes("Old price"), text);
        check("the card says the sensor is gone", text.includes(missingSensorLabel(404, true)), text);
        eq("and the stale copy is forgotten", localStorage.getItem("sensor_404"), null);

        const intact = await renderAssetPlotCard({asset: 2, "flex-context": "consumption-price"}, () => {}, 0, 0);
        eq("an asset plot without such a reference reports nothing gone", intact.missing, false);
        localStorage.clear();
        """)
