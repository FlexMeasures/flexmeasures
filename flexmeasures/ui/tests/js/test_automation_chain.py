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
              "depends-on": [{{automation: 7, "allow-failure": true}}, {{automation: 5, "allow-failure": false}},
                             {{automation: 4, "allow-failure": false, name: "Public prices", asset: 2, "asset-name": "NL zone"}}]}},
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
        eq("one that may not be read has nowhere to link to", node(5).querySelector("a"), null);
        eq("one that may not be read stays a bare ID", node(5).querySelector("title").textContent, "5 (not listed here)");
        eq("one that may be read, but is not listed here, links to its own asset",
           node(4).querySelector("a").getAttribute("href"), "/assets/2/automations?automation=4");
        eq("hovering tells as much as is known about one that is not listed here",
           node(4).querySelector("title").textContent.split("\\n"), ["4: Public prices", "On NL zone (asset 2)", "Not listed here"]);
        check("its box names it", node(4).querySelector("text").textContent.includes("Public prices"));
        eq("hovering over an arrow says what a failure does",
           [...doc.querySelectorAll(".chain-arrow")].map((arrow) => arrow.parentNode.querySelector("title").textContent),
           ["Forecast runs even if Pull <meter> data fails", "Forecast is skipped if Automation 5 fails", "Forecast is skipped if Public prices fails"]);
        check("what the arrows mean is spelled out", doc.body.textContent.includes("unless that arrow is dashed"));

        document.body.insertAdjacentHTML("beforeend", '<button id="mock-ingestion-tab"></button><div id="AutomationInfoModal-7"></div>');
        page.openLinkedAutomation(7);
        eq("the tab of its type comes first, as a panel in a hidden tab does not open", opened, ["mock-ingestion-tab", "AutomationInfoModal-7"]);
    """)


def test_the_scope_decides_what_the_waits_for_list_and_the_chain_go_by(assert_js):
    script = automation_script(can_manage=True, can_run=True)
    assert_js(f"""
        // Keep the page's ready callback from trying to fetch data; exercise its helpers directly.
        window.$ = () => ({{ready: () => {{}}}});
        const page = new Function({json.dumps(script)} + `
            \\nreturn {{ fillDependsOnPicker, chainGraph, automationsById, scopedAutomations, setScope: (scope) => {{ automationScope = scope; }} }};`)();
        document.body.insertAdjacentHTML("beforeend", '<div id="picker"></div>');
        const details = {{type: "forecasting", "asset-name": "site", cron: "0 * * * *", timezone: "UTC", "recurrence-description": "Every hour", active: true}};
        // 7 is on this asset (3), 8 on a sub-asset waiting for 7, and 20 on a public asset, which 7 waits for.
        for (const automation of [
            {{...details, id: 7, name: "Pull", asset: 3, "depends-on": [{{automation: 20, "allow-failure": false}}]}},
            {{...details, id: 8, name: "Forecast", asset: 4, "depends-on": [{{automation: 7, "allow-failure": false}}]}},
        ]) {{
            page.automationsById.set(automation.id, automation);
        }}
        const prices = {{...details, id: 20, name: "Public prices", asset: 1, "asset-name": "NL", "depends-on": []}};
        page.scopedAutomations.set("public", [prices]);
        page.scopedAutomations.set("all", [...page.automationsById.values(), prices]);
        const offered = () => [...document.querySelectorAll("#picker input")].map((box) => Number(box.value));
        const drawn = (id) => [...new DOMParser().parseFromString(page.chainGraph(id), "text/html").querySelectorAll(".chain-node")]
            .map((node) => Number(node.dataset.automationId)).sort((a, b) => a - b);

        page.fillDependsOnPicker("#picker");
        eq("by default, the list holds what is on this page", offered(), [7, 8]);
        page.setScope("asset");
        page.fillDependsOnPicker("#picker");
        eq("it can narrow down to this asset", offered(), [7]);
        page.setScope("public");
        page.fillDependsOnPicker("#picker");
        eq("it can show public automations", offered(), [20]);
        page.setScope("all");
        page.fillDependsOnPicker("#picker", 7);
        eq("it can show everything, except the automation being edited", offered(), [8, 20]);
        page.setScope("public");
        page.fillDependsOnPicker("#picker", null, [{{automation: 8}}]);
        eq("what it already waits for stays on offer", offered(), [20, 8]);
        check("and keeps its name", document.querySelector("#picker").textContent.includes("8: Forecast"));

        page.setScope("all");
        eq("a chain follows every automation in scope", drawn(8), [7, 8, 20]);
        const title = new DOMParser().parseFromString(page.chainGraph(8), "text/html").querySelector('.chain-node[data-automation-id="20"] title');
        check("with all there is to tell about one beyond this page", title.textContent.includes("Every hour"));
        page.setScope("public");
        eq("and stops where the scope ends, at what is waited for", drawn(8), [7, 8]);
    """)


def test_a_validation_error_reads_as_a_sentence(assert_js):
    script = automation_script(can_manage=True, can_run=True)
    assert_js(f"""
        // Keep the page's ready callback from trying to fetch data; exercise its helpers directly.
        window.$ = () => ({{ready: () => {{}}}});
        const page = new Function({json.dumps(script)} + "\\nreturn {{ automationAjaxErrorMessage, apiError }};")();
        const loop = "Automation 3 would end up waiting for itself.";
        const body = {{message: {{json: {{"depends-on": [loop]}}}}}};
        eq("the loop error says just that", page.apiError({{responseText: JSON.stringify(body)}}, "fallback"), loop);
        eq("the same goes for the other way of reporting one", page.automationAjaxErrorMessage({{responseJSON: body}}), loop);
        eq("another field is named", page.apiError({{responseText: JSON.stringify({{message: {{cron: ["Not a valid cron string."]}}}})}}, "fallback"),
           "cron: Not a valid cron string.");
        eq("a plain message stays as it is", page.apiError({{responseText: JSON.stringify({{message: "Nope"}})}}, "fallback"), "Nope");
    """)


def test_deleting_an_automation_tells_what_waits_for_it(assert_js):
    script = automation_script(can_manage=True, can_run=True)
    assert_js(f"""
        // Keep the page's ready callback from trying to fetch data; exercise its helpers directly.
        window.$ = () => ({{ready: () => {{}}}});
        const page = new Function({json.dumps(script)} + "\\nreturn {{ deleteQuestion }};")();
        eq("nothing waiting, nothing to tell", page.deleteQuestion("Pull", []), "Delete automation 'Pull'?");
        eq("details out of reach, nothing to tell", page.deleteQuestion("Pull", null), "Delete automation 'Pull'?");
        const question = page.deleteQuestion("Pull", [{{automation: 8, name: "Forecast"}}, {{automation: 5}}]);
        check("what waits for it is named", question.includes("- 8: Forecast"));
        check("one that may not be read is a bare ID", question.includes("- Automation 5"));
        check("and it says what comes of them", question.includes("will run without it from now on"));
    """)


def test_a_run_plan_shows_what_runs_and_lets_a_branch_be_left_out(assert_js):
    script = automation_script(can_manage=True, can_run=True)
    assert_js(f"""
        // Keep the page's ready callback from trying to fetch data; exercise its helpers directly.
        window.$ = () => ({{ready: () => {{}}}});
        const page = new Function({json.dumps(script)} + "\\nreturn {{ runPlanSelection, runPlanStructure, runPlanBranches, runPlanHtml, runPlanQuery, AutomationRow, automationsById }};")();
        // 9 waits for 4 and 7, and 7 waits for 2 and 5, of which 5 is one the user may not run.
        const steps = [
            {{automation: 5, "waits-for": [], "will-run": false, reason: "You may not run this automation."}},
            {{automation: 2, "waits-for": [], "will-run": true, name: "Tariffs", "asset-name": "site"}},
            {{automation: 4, "waits-for": [], "will-run": true, name: "Meters", "asset-name": "site"}},
            {{automation: 7, "waits-for": [2, 5], "will-run": true, name: "Prices", "asset-name": "site"}},
            {{automation: 9, "waits-for": [4, 7], "will-run": true, name: "<b>Forecast</b>", "asset-name": "site"}},
        ];
        const plan = {{automationId: 9, direction: "ascendants", steps, leftOut: new Set()}};
        eq("what may not run is left out", page.runPlanSelection(plan), [2, 4, 7, 9]);
        eq("the IDs show the order, with what can run side by side next to each other", page.runPlanStructure(plan), "2, 4 → 7 → 9");
        eq("only automations that come together can be chosen between", [...page.runPlanBranches(plan)].sort(), [4, 7]);
        const doc = new DOMParser().parseFromString(page.runPlanHtml(plan), "text/html");
        const row = (id) => doc.querySelector(`li[data-automation-id="${{id}}"]`);
        check("what will not run says why", row(5).textContent.includes("Won't run. You may not run this automation."));
        check("it has no box to tick", row(5).querySelector("input") === null);
        check("a branch has a ticked box", row(7).querySelector("input").checked);
        check("this automation is pointed out", row(9).textContent.includes("This automation"));
        eq("a name stays text", row(9).querySelector("b"), null);
        check("the rest is said to go by the latest results", doc.body.textContent.includes("latest results of those that won't run"));
        eq("nothing is left out by default", page.runPlanQuery(plan), "with-ascendants=true");

        plan.leftOut.add(7);
        eq("leaving out a branch takes along what only it needs", page.runPlanSelection(plan), [4, 9]);
        eq("the IDs follow", page.runPlanStructure(plan), "4 → 9");
        eq("and so does the request", page.runPlanQuery(plan), "with-ascendants=true&leave-out=7");
        const unticked = new DOMParser().parseFromString(page.runPlanHtml(plan), "text/html");
        check("its box stays there to tick again", !unticked.querySelector('li[data-automation-id="7"] input').checked);
        check("what only it needs says it won't run", unticked.querySelector('li[data-automation-id="2"]').textContent.includes("Won't run."));
        check("an automation only says it waits for what runs", unticked.querySelector('li[data-automation-id="9"]').textContent.includes("Waits for 4")
              && !unticked.querySelector('li[data-automation-id="9"]').textContent.includes("Waits for 4, 7"));

        const down = {{automationId: 2, direction: "dependents", leftOut: new Set(), steps: [
            {{automation: 2, "waits-for": [], "will-run": true, name: "Tariffs"}},
            {{automation: 7, "waits-for": [2], "will-run": true, name: "Prices"}},
        ]}};
        eq("dependents show the same way", page.runPlanStructure(down), "2 → 7");
        eq("and there is nothing to choose between", page.runPlanBranches(down).size, 0);
        eq("and their request is as before", page.runPlanQuery(down), "with-dependents=true");
        const refused = {{...down, steps: [down.steps[0], {{...down.steps[1], "will-run": false, reason: "You may not run this automation."}}]}};
        check("dependents one may not run are refused as a whole", page.runPlanHtml(refused).includes("cannot be run"));

        const row8 = page.AutomationRow({{id: 8, name: "Forecast", type: "forecasting", active: true, "depends-on": [{{automation: 4}}]}});
        const row4 = page.AutomationRow({{id: 4, name: "Meters", type: "forecasting", active: true, "depends-on": []}});
        check("an automation that waits for another offers to run with ascendants", row8.actions.includes("Run with ascendants"));
        check("one that waits for nothing does not", !row4.actions.includes("Run with ascendants"));
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
