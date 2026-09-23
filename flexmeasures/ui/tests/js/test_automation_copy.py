"""Browser checks for copying an automation into the automation page's creation form."""

import json
import re
from pathlib import Path

import pytest

TEMPLATE = (
    Path(__file__).resolve().parents[2] / "templates/assets/asset_automations.html"
)


@pytest.fixture(scope="module", autouse=True)
def setup_ui_test_data():
    """The inline-script checks do not need the UI suite's database fixtures."""


def copy_script(can_manage: bool = True) -> str:
    """Render the page's inline JavaScript, with the three Jinja values it reads filled in."""
    match = re.search(r"<script>(.*?)</script>", TEMPLATE.read_text(), re.DOTALL)
    assert match is not None
    return (
        match.group(1)
        .replace("{{ asset.id }}", "3")
        .replace("{{ user_can_manage_automations | tojson }}", str(can_manage).lower())
        .replace("{{ user_can_create_children | tojson }}", "true")
    )


def creation_form_html() -> str:
    """The creation form as the page renders it, so the checks run against the real fields."""
    match = re.search(
        r'(<form id="newAutomationForm">.*?</form>)', TEMPLATE.read_text(), re.DOTALL
    )
    assert match is not None
    return match.group(1).replace("{{ asset.timezone }}", "Europe/Amsterdam")


# A stand-in for the handful of jQuery calls the form helpers make, backed by the real DOM.
JQUERY_STUB = """
    window.$ = function (selector) {
        const nodes = typeof selector === "string" ? [...document.querySelectorAll(selector)] : [];
        const self = {
            ready: () => {},
            on: () => self,
            val: function (value) {
                if (value === undefined) return nodes.length ? nodes[0].value : undefined;
                nodes.forEach(node => { node.value = value; });
                return self;
            },
            prop: function (name, value) {
                nodes.forEach(node => { node[name] = value; });
                return self;
            },
            is: (what) => what === ":checked" && nodes.length > 0 && nodes[0].checked,
            text: function (value) {
                nodes.forEach(node => { node.textContent = value; });
                return self;
            },
            empty: function () {
                nodes.forEach(node => { node.innerHTML = ""; });
                return self;
            },
            addClass: function (name) {
                nodes.forEach(node => node.classList.add(name));
                return self;
            },
            removeClass: function (name) {
                nodes.forEach(node => node.classList.remove(name));
                return self;
            },
            toggleClass: function (name, on) {
                nodes.forEach(node => node.classList.toggle(name, on));
                return self;
            },
        };
        return self;
    };
"""


def test_a_copy_carries_the_settings_over_and_starts_inactive(assert_js):
    """A copy recreates the original on the same asset, except that it does not start running."""
    assert_js(f"""
        window.$ = () => ({{ready: () => {{}}}});
        const page = new Function({json.dumps(copy_script())}
            + "\\nreturn {{ automationCopyValues, copiedAutomationName }};")();

        const automation = {{
            id: 7, name: "Campus forecast", type: "forecasting", active: true,
            "cron": "0 6 * * *", timezone: "Europe/Amsterdam",
        }};
        const details = {{parameters: {{sensor: 2092, "start-offset": "1D,DB"}}, source: {{id: 6, description: "Seita's forecaster"}}}};
        const values = page.automationCopyValues(automation, details);

        eq("the copy is marked as one in its name", values.name, "Campus forecast (copy)");
        eq("the recurrence is carried over", values.cron, "0 6 * * *");
        eq("and so is the timezone it is read in", values.timezone, "Europe/Amsterdam");
        eq("the type is carried over", values.type, "forecasting");
        eq("the parameters are carried over as stored", JSON.parse(values.parameters), details.parameters);
        eq("a copy of an active automation still starts inactive", values.active, false);
        eq("a forecast copy reuses the original's data source", values.sourceId, 6);
    """)


def test_a_copy_only_reuses_a_data_source_where_one_can_be_named(assert_js):
    """A schedule automation resolves its source on every run, so a copy of one must not name the original's."""
    assert_js(f"""
        window.$ = () => ({{ready: () => {{}}}});
        const page = new Function({json.dumps(copy_script())}
            + "\\nreturn {{ automationCopyValues }};")();

        const source = {{id: 6, description: "Seita's generator"}};
        const scheduleCopy = page.automationCopyValues(
            {{id: 8, name: "Battery schedule", type: "scheduling", "cron": "0 * * * *", timezone: "UTC"}},
            {{parameters: {{}}, source: source}});
        eq("a schedule copy names no data source", scheduleCopy.sourceId, null);

        const reportCopy = page.automationCopyValues(
            {{id: 9, name: "Weekly report", type: "reporting", "cron": "0 0 * * 1", timezone: "UTC"}},
            {{parameters: {{}}, source: source}});
        eq("a report copy reuses the original's data source", reportCopy.sourceId, 6);

        const sourceless = page.automationCopyValues(
            {{id: 10, name: "Orphan", type: "forecasting", "cron": "0 0 * * *", timezone: "UTC"}},
            {{parameters: {{}}}});
        eq("an automation whose details carry no source names none", sourceless.sourceId, null);
        eq("and its parameters still default to an empty object", JSON.parse(sourceless.parameters), {{}});
    """)


def test_a_long_name_keeps_the_suffix_that_marks_the_copy(assert_js):
    """The name field and the API both stop at 80 characters, so the tail goes rather than the suffix."""
    assert_js(f"""
        window.$ = () => ({{ready: () => {{}}}});
        const page = new Function({json.dumps(copy_script())}
            + "\\nreturn {{ copiedAutomationName }};")();

        const long = page.copiedAutomationName("x".repeat(120));
        eq("a long name is cut to what the field holds", long.length, 80);
        check("and still says it is a copy", long.endsWith(" (copy)"), long);
        eq("a short name is left alone apart from the suffix",
           page.copiedAutomationName("Campus forecast"), "Campus forecast (copy)");
    """)


def test_opening_a_blank_form_clears_what_a_copy_left_in_it(assert_js):
    """The creation form is shared with the Copy action, so New automation has to clear it rather than inherit a copy."""
    assert_js(f"""
        // Appended rather than assigned to the body, which holds the harness's own results element.
        const holder = document.createElement("div");
        holder.innerHTML = {json.dumps(creation_form_html())};
        document.body.appendChild(holder);
        {JQUERY_STUB}
        const page = new Function({json.dumps(copy_script())}
            + "\\nreturn {{ prefillNewAutomationForm, resetNewAutomationForm, automationCopyValues }};")();

        const values = page.automationCopyValues(
            {{id: 7, name: "Campus forecast", type: "reporting", "cron": "30 7 * * *", timezone: "Africa/Tunis"}},
            {{parameters: {{sensor: 2092}}, source: {{id: 6}}}});
        page.prefillNewAutomationForm(values);

        eq("the copy fills the name in", document.getElementById("automationName").value, "Campus forecast (copy)");
        eq("and the recurrence", document.getElementById("automationCron").value, "30 7 * * *");
        eq("and the timezone", document.getElementById("automationTimezone").value, "Africa/Tunis");
        eq("and the type", document.getElementById("automationType").value, "reporting");
        eq("and the parameters", JSON.parse(document.getElementById("automationParameters").value), {{sensor: 2092}});
        eq("and leaves the copy inactive", document.getElementById("automationActive").checked, false);

        page.resetNewAutomationForm();

        eq("opening a blank form clears the copied name", document.getElementById("automationName").value, "");
        eq("and the copied recurrence", document.getElementById("automationCron").value, "");
        eq("and the copied parameters", document.getElementById("automationParameters").value, "");
        eq("and restores the asset's own timezone",
           document.getElementById("automationTimezone").value, "Europe/Amsterdam");
        eq("and the default type", document.getElementById("automationType").value, "forecasting");
        eq("and a new automation is active again, as the form is rendered",
           document.getElementById("automationActive").checked, true);
        check("and the data generator fields are usable again, whatever the copy did to them",
              !document.getElementById("automationGenerator").disabled
              && !document.getElementById("automationConfig").disabled, "still disabled");
    """)


def test_copy_is_offered_to_managers_only(assert_js):
    """Copying creates an automation, so it sits behind the same permission as creating one."""
    manager_script = copy_script(can_manage=True)
    viewer_script = copy_script(can_manage=False)
    assert_js(f"""
        window.$ = () => ({{ready: () => {{}}}});
        const manager = new Function({json.dumps(manager_script)} + "\\nreturn {{ AutomationRow }};")();
        const viewer = new Function({json.dumps(viewer_script)} + "\\nreturn {{ AutomationRow }};")();
        const automation = {{
            id: 7, name: "Campus forecast", type: "forecasting", active: true,
            "created-at": null, "cron": "0 6 * * *", timezone: "Europe/Amsterdam",
            "recurrence-description": "At 06:00", "next-run": null,
        }};
        const managerRow = manager.AutomationRow(automation);
        check("a manager is offered Copy", managerRow.actions.includes("automation-copy"), managerRow.actions);
        check("and it carries the id to copy", managerRow.actions.includes('class="dropdown-item automation-copy" data-id="7"'),
              managerRow.actions);
        const viewerRow = viewer.AutomationRow(automation);
        check("someone who may not manage automations is not offered Copy",
              !viewerRow.actions.includes("automation-copy"), viewerRow.actions);
    """)
