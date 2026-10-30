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
            page.automationsById.set(automation.id, automation);
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
              && svg.querySelector('.chain-node[data-automation-id="9"] title').textContent.endsWith("community"));
        check("an automation outside any chain says so", page.chainGraph(10).includes("No automation listed here"));
        eq("only an automation that another listed one waits for offers to run with dependents",
           [7, 8, 9, 10].map((id) => page.hasListedDependents({{id}})), [true, true, false, false]);
    """)
