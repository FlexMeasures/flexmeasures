"""Browser checks for the chain of automations drawn in an automation's details."""

import json

import pytest

# The page's script is rendered by one helper, which asserts that it leaves no Jinja value behind.
from test_automation_actions import automation_script


@pytest.fixture(scope="module", autouse=True)
def setup_ui_test_data():
    """The inline-script checks do not need the UI suite's database fixtures."""


def test_the_chain_of_an_automation_is_drawn_from_first_to_last(assert_js):
    script = automation_script(can_manage=True, can_run=True)
    assert_js(f"""
        // Keep the page's ready callback from trying to fetch data; exercise its helpers directly.
        window.$ = () => ({{ready: () => {{}}}});
        const page = new Function({json.dumps(script)} + "\\nreturn {{ chainGraph, automationsById, hasListedDependents }};")();
        // Automation 5 is not listed here, 7 and 5 are waited for by 8, 8 by 9 (also when it fails), and 10 stands apart.
        for (const automation of [
            {{id: 7, name: "Pull meter data", "depends-on": []}},
            {{id: 8, name: "Net report", "depends-on": [{{automation: 7, "allow-failure": false}}, {{automation: 5, "allow-failure": false}}]}},
            {{id: 9, name: "Forecast the net consumption of the community", "depends-on": [{{automation: 8, "allow-failure": true}}]}},
            {{id: 10, name: "Unrelated", "depends-on": []}},
        ]) {{
            page.automationsById.set(automation.id, {{
                type: "forecasting", asset: 3, "asset-name": "site", "recurrence-description": "Every hour", timezone: "UTC", active: true, ...automation,
            }});
        }}
        const svg = new DOMParser().parseFromString(page.chainGraph(8), "text/html").querySelector("svg");
        const nodes = [...svg.querySelectorAll(".chain-node")];
        const x = (id) => Number(svg.querySelector(`.chain-node[data-automation-id="${{id}}"] rect`).getAttribute("x"));
        eq("the chain holds what this one waits for and what waits for it, and nothing else",
           nodes.map((node) => Number(node.dataset.automationId)).sort(), [5, 7, 8, 9]);
        eq("the automations waited for come first", [x(5) === x(7), x(7) < x(8), x(8) < x(9)], [true, true, true]);
        eq("this automation stands out", svg.querySelector(".chain-node-current").dataset.automationId, "8");
        eq("an automation not listed here says so", svg.querySelector('.chain-node[data-automation-id="5"] title').textContent, "5 (not listed here)");
        eq("one arrow per dependency, dashed where failure is allowed",
           [...svg.querySelectorAll(".chain-arrow")].map((arrow) => arrow.hasAttribute("stroke-dasharray")).sort(), [false, false, true]);
        check("a long name is cut short, and kept whole in its tooltip",
              svg.querySelector('.chain-node[data-automation-id="9"] text').textContent.endsWith("…")
              && svg.querySelector('.chain-node[data-automation-id="9"] title').textContent.includes("community"));
        check("an automation outside any chain says so", page.chainGraph(10).includes("No automation listed here"));
        eq("only an automation that another listed one waits for offers to run with dependents",
           [7, 8, 9, 10].map((id) => page.hasListedDependents({{id}})), [true, true, false, false]);
    """)


def test_a_chain_tells_more_on_hover_and_links_to_its_automations(assert_js):
    script = automation_script(can_manage=True, can_run=True)
    assert_js(f"""
        // Keep the page's ready callback from trying to fetch data; exercise its helpers directly.
        window.$ = () => ({{ready: () => {{}}}});
        const opened = [];
        const opener = {{getOrCreateInstance: (element) => ({{show: () => opened.push(element.id)}})}};
        window.bootstrap = {{Tab: opener, Modal: opener}};
        const page = new Function({json.dumps(script)} + "\\nreturn {{ chainGraph, automationsById, openLinkedAutomation }};")();
        for (const automation of [
            {{id: 7, type: "mock-ingestion", name: "Pull <meter> data", asset: 3, "asset-name": "site", "recurrence-description": "Every hour", timezone: "UTC", active: true, "depends-on": []}},
            {{id: 8, type: "forecasting", name: "Forecast", asset: 12, "asset-name": "battery", "recurrence-description": "Every day", timezone: "Europe/Amsterdam", active: false,
              "depends-on": [{{automation: 7, "allow-failure": true}}, {{automation: 5, "allow-failure": false}}]}},
        ]) {{
            page.automationsById.set(automation.id, automation);
        }}
        const doc = new DOMParser().parseFromString(page.chainGraph(7), "text/html");
        const node = (id) => doc.querySelector(`.chain-node[data-automation-id="${{id}}"]`);
        eq("hovering tells the type, the asset and its ID, the recurrence and whether it is active",
           node(8).querySelector("title").textContent.split("\\n"),
           ["8: Forecast", "Forecasts", "On battery (asset 12)", "Every day, Europe/Amsterdam", "Inactive"]);
        eq("another automation links to its own asset, with its details open",
           node(8).querySelector("a").getAttribute("href"), "/assets/12/automations?automation=8");
        eq("the one being read links nowhere", node(7).querySelector("a"), null);
        eq("one that is not listed here has nowhere to link to", node(5).querySelector("a"), null);
        eq("hovering over an arrow says what a failure does",
           [...doc.querySelectorAll(".chain-arrow")].map((arrow) => arrow.parentNode.querySelector("title").textContent),
           ["Forecast runs even if Pull <meter> data fails", "Forecast is skipped if Automation 5 fails"]);
        check("what the arrows mean is spelled out", doc.body.textContent.includes("unless that arrow is dashed"));

        document.body.insertAdjacentHTML("beforeend", '<button id="mock-ingestion-tab"></button><div id="AutomationInfoModal-7"></div>');
        page.openLinkedAutomation(7);
        eq("the tab of its type comes first, as a panel in a hidden tab does not open", opened, ["mock-ingestion-tab", "AutomationInfoModal-7"]);
    """)


def test_the_waits_for_picker_ticks_what_an_automation_waits_for(assert_js):
    script = automation_script(can_manage=True, can_run=True)
    assert_js(f"""
        // Keep the page's ready callback from trying to fetch data; exercise its helpers directly.
        window.$ = () => ({{ready: () => {{}}}});
        const page = new Function({json.dumps(script)} + "\\nreturn {{ fillDependsOnPicker, dependsOnValues, automationsById }};")();
        document.body.insertAdjacentHTML("beforeend", '<div id="picker"></div><input type="checkbox" id="allowFailure">');
        for (const automation of [
            {{id: 7, name: "Pull meter data", "asset-name": "site", cron: "0 * * * *", timezone: "UTC"}},
            {{id: 8, name: "<b>Net report</b>", "asset-name": "site", cron: "*/15 * * * *", timezone: "UTC"}},
            {{id: 9, name: "Forecast", "asset-name": "battery", cron: "0 6 * * *", timezone: "UTC"}},
        ]) {{
            page.automationsById.set(automation.id, automation);
        }}
        page.fillDependsOnPicker("#picker", 9, [{{automation: 7, "allow-failure": false}}, {{automation: 5, "allow-failure": false}}]);
        const rows = [...document.querySelectorAll("#picker label")];
        const boxes = () => [...document.querySelectorAll("#picker input")];
        eq("every other automation is offered, and one on another page is kept", boxes().map((box) => box.value), ["7", "8", "5"]);
        eq("what it waits for is ticked", boxes().map((box) => box.checked), [true, false, true]);
        check("a row names the asset and the recurrence", rows[1].textContent.includes("site, */15 * * * *, UTC"));
        eq("a name stays text", rows[1].querySelector("b"), null);
        rows[1].click();
        eq("a click anywhere on a row ticks its box, and is sent along",
           page.dependsOnValues("#picker", "#allowFailure").map((dependency) => dependency.automation), [7, 8, 5]);
    """)
