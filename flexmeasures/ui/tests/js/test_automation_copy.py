"""Browser checks for copying an automation into the automation page's creation form."""

import json
import re

from jinja2 import Environment, StrictUndefined
import pytest

# The page's script is rendered by one helper, which asserts that it leaves no Jinja value behind.
# Sharing it keeps these checks from breaking whenever the page reads another value.
from test_automation_actions import (
    PLUGIN_AUTOMATION_TYPES,
    TEMPLATE,
    automation_script,
    automation_tabs_html,
)


@pytest.fixture(scope="module", autouse=True)
def setup_ui_test_data():
    """The inline-script checks do not need the UI suite's database fixtures."""


def copy_script(can_manage: bool = True, can_change_monitoring: bool = True) -> str:
    """Render the page's inline JavaScript, as someone who may copy an automation sees it."""
    return automation_script(
        can_manage=can_manage,
        can_run=True,
        can_change_monitoring=can_change_monitoring,
    )


def creation_form_html(can_change_monitoring: bool = True) -> str:
    """The creation form as the page renders it, so the checks run against the real fields."""
    match = re.search(
        r'(<form id="newAutomationForm">.*?</form>)', TEMPLATE.read_text(), re.DOTALL
    )
    assert match is not None
    environment = Environment(autoescape=True, undefined=StrictUndefined)
    return environment.from_string(match.group(1)).render(
        asset={"timezone": "Europe/Amsterdam"},
        plugin_automation_types=PLUGIN_AUTOMATION_TYPES,
        user_can_change_monitoring=can_change_monitoring,
    )


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
            attr: function (name, value) {
                if (value === undefined) return nodes.length ? nodes[0].getAttribute(name) : undefined;
                nodes.forEach(node => node.setAttribute(name, value));
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
            toggle: function (on) {
                nodes.forEach(node => { node.style.display = on ? "" : "none"; });
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
        eq("a copy of a monitored automation is monitored", values.monitored, true);
        eq("and one of an unmonitored automation is not",
           page.automationCopyValues({{...automation, monitored: false}}, details).monitored, false);
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
        const pluginCopy = page.automationCopyValues(
            {{id: 11, name: "Site import", type: "mock-ingestion", "cron": "*/15 * * * *", timezone: "UTC"}},
            {{parameters: {{}}, source: source}});
        eq("a plugin copy reuses the original's data source", pluginCopy.sourceId, 6);

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
            {{id: 7, name: "Campus forecast", type: "reporting", "cron": "30 7 * * *", timezone: "Africa/Tunis", monitored: false}},
            {{parameters: {{sensor: 2092}}, source: {{id: 6}}}});
        page.prefillNewAutomationForm(values);

        eq("the copy fills the name in", document.getElementById("automationName").value, "Campus forecast (copy)");
        eq("and the recurrence", document.getElementById("automationCron").value, "30 7 * * *");
        eq("and the timezone", document.getElementById("automationTimezone").value, "Africa/Tunis");
        eq("and the type", document.getElementById("automationType").value, "reporting");
        eq("and the parameters", JSON.parse(document.getElementById("automationParameters").value), {{sensor: 2092}});
        eq("and leaves the copy inactive", document.getElementById("automationActive").checked, false);
        eq("and unmonitored, as its original is", document.getElementById("automationMonitored").checked, false);

        const generatorFields = () => [...document.querySelectorAll(".chooses-generator")];
        check("a report copy can still name a data generator",
              generatorFields().length > 0 && generatorFields().every(field => field.style.display !== "none"),
              "hidden for a type that chooses its own generator");

        // A schedule automation works its generator out from the asset on every run, so a copy of one may not name it.
        page.prefillNewAutomationForm(page.automationCopyValues(
            {{id: 8, name: "Battery schedule", type: "scheduling", "cron": "0 * * * *", timezone: "UTC"}},
            {{parameters: {{}}, source: {{id: 6}}}}));
        check("a schedule copy hides the data generator fields",
              generatorFields().every(field => field.style.display === "none"),
              "still shown for a schedule automation");

        page.resetNewAutomationForm();

        eq("opening a blank form clears the copied name", document.getElementById("automationName").value, "");
        eq("and the copied recurrence", document.getElementById("automationCron").value, "");
        eq("and the copied parameters", document.getElementById("automationParameters").value, "");
        eq("and restores the asset's own timezone",
           document.getElementById("automationTimezone").value, "Europe/Amsterdam");
        eq("and the default type", document.getElementById("automationType").value, "forecasting");
        eq("and a new automation is active again, as the form is rendered",
           document.getElementById("automationActive").checked, true);
        eq("and monitored again", document.getElementById("automationMonitored").checked, true);
        check("and the data generator fields are shown again, after a schedule copy hid them",
              generatorFields().every(field => field.style.display !== "none"), "still hidden");
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


def test_the_form_offers_installed_plugin_types_and_asks_them_for_no_generator_class(
    assert_js,
):
    """A plugin type declares its own data generator, so the form takes its config and parameters but no generator class."""
    assert_js(f"""
        const holder = document.createElement("div");
        holder.innerHTML = {json.dumps(creation_form_html())};
        document.body.appendChild(holder);
        {JQUERY_STUB}
        const page = new Function({json.dumps(copy_script())}
            + "\\nreturn {{ prefillNewAutomationForm, resetNewAutomationForm, automationCopyValues, typeNamesGeneratorClass }};")();

        const pluginOption = document.querySelector('#automationType optgroup[label="Plugin types"] option[value="mock-ingestion"]');
        check("an installed plugin type is offered under Plugin types", pluginOption !== null, document.getElementById("automationType").innerHTML);
        eq("and named as its tab names it", pluginOption.textContent.trim(), "Mock ingestion");

        page.prefillNewAutomationForm(page.automationCopyValues(
            {{id: 11, name: "Site import", type: "mock-ingestion", "cron": "*/15 * * * *", timezone: "UTC"}},
            {{parameters: {{}}, source: {{id: 6}}}}));
        const shown = selector => [...document.querySelectorAll(selector)].every(node => node.style.display !== "none");
        const hidden = selector => [...document.querySelectorAll(selector)].every(node => node.style.display === "none");
        eq("a plugin copy keeps its type", document.getElementById("automationType").value, "mock-ingestion");
        check("a plugin type still takes a config and a data source",
              shown("#automationConfig") && document.getElementById("automationConfig").closest(".chooses-generator").style.display !== "none"
              && document.getElementById("automationSourceSearch").closest(".chooses-generator").style.display !== "none",
              "config or source picker hidden");
        check("but asks for no data generator class", hidden(".names-generator-class"), "generator class field shown");
        check("nor for the run period options of the built-in types", hidden(".builtin-type-only"), "run period hint shown");
        eq("and sends none", page.typeNamesGeneratorClass(), false);

        page.resetNewAutomationForm();
        check("a forecast names its data generator class again", shown(".names-generator-class"), "generator class field still hidden");
        check("and gets the run period options back", shown(".builtin-type-only"), "run period hint still hidden");
        eq("and sends its class", page.typeNamesGeneratorClass(), true);
    """)


def test_the_examples_in_the_form_follow_the_chosen_type(assert_js):
    """Each type's empty fields show an example of that type, and a plugin type's show what its schemas load."""
    assert_js(f"""
        const holder = document.createElement("div");
        holder.innerHTML = {json.dumps(creation_form_html())};
        document.body.appendChild(holder);
        {JQUERY_STUB}
        const page = new Function({json.dumps(copy_script())}
            + "\\nreturn {{ showGeneratorFields }};")();
        const placeholder = id => document.getElementById(id).getAttribute("placeholder");
        const choose = type => {{ document.getElementById("automationType").value = type; page.showGeneratorFields(); }};

        choose("forecasting");
        eq("a forecast suggests its default forecaster", placeholder("automationGenerator"), "TrainPredictPipeline");
        choose("reporting");
        eq("a report suggests a reporter", placeholder("automationGenerator"), "PandasReporter");
        check("and a report's parameters", placeholder("automationParameters").includes('"output"'), placeholder("automationParameters"));
        choose("mock-ingestion");
        eq("a plugin type suggests the config its schema loads", placeholder("automationConfig"), '{{"sensor": "...", "input-sensor": "..."}}');
        eq("and the parameters, with their defaults", placeholder("automationParameters"), '{{"value": 42.0}}');
    """)


def test_a_new_automation_starts_as_the_type_of_the_tab_in_front(assert_js):
    """New automation starts from the tab the user is on, when the form offers that type."""
    assert_js(f"""
        const holder = document.createElement("div");
        holder.innerHTML = {json.dumps(creation_form_html())} + {json.dumps(automation_tabs_html())};
        document.body.appendChild(holder);
        {JQUERY_STUB}
        const page = new Function({json.dumps(copy_script())}
            + "\\nreturn {{ typeOfTabInFront, formOffersType }};")();

        eq("the first tab is in front at first", page.typeOfTabInFront(), "forecasting");
        document.getElementById("forecasting-tab").classList.remove("active");
        document.getElementById("mock-ingestion-tab").classList.add("active");
        eq("the plugin tab in front gives its type", page.typeOfTabInFront(), "mock-ingestion");
        check("which the form offers", page.formOffersType("mock-ingestion"), "");
        check("unlike a type whose plugin is gone", !page.formOffersType("gone-plugin"), "");
    """)


def test_deleting_the_last_automation_of_a_plugin_type_says_how_to_make_one_again(
    assert_js,
):
    """Its tab goes with it, so the user is told that New automation still makes one."""
    assert_js(f"""
        const holder = document.createElement("div");
        holder.innerHTML = {json.dumps(creation_form_html())};
        document.body.appendChild(holder);
        {JQUERY_STUB}
        const page = new Function({json.dumps(copy_script())}
            + "\\nreturn {{ lastOfItsTypeDeletedMessage, list: (automations) => {{"
            + " lastListedAutomations = automations; automations.forEach(a => automationsById.set(a.id, a)); }} }};")();

        page.list([{{id: 1, type: "mock-ingestion"}}, {{id: 2, type: "mock-ingestion"}}, {{id: 3, type: "forecasting"}}, {{id: 4, type: "gone-plugin"}}]);
        eq("deleting one of two says nothing", page.lastOfItsTypeDeletedMessage(1), null);
        eq("nor does deleting the last of a type whose tab always shows", page.lastOfItsTypeDeletedMessage(3), null);
        eq("nor the last of a type whose plugin is gone, which cannot be made again", page.lastOfItsTypeDeletedMessage("4"), null);

        page.list([{{id: 2, type: "mock-ingestion"}}]);
        eq("deleting the last one says where to make a new one", page.lastOfItsTypeDeletedMessage("2"),
           "That was the last Mock ingestion automation here. To make a new one, use New automation.");
    """)


def test_only_admins_can_switch_monitoring_in_the_form(assert_js):
    """Someone who may not switch monitoring off finds the checkbox disabled, and a copy of an unmonitored automation monitored."""
    assert_js(f"""
        const holder = document.createElement("div");
        holder.innerHTML = {json.dumps(creation_form_html(can_change_monitoring=False))};
        document.body.appendChild(holder);
        {JQUERY_STUB}
        const page = new Function({json.dumps(copy_script(can_change_monitoring=False))}
            + "\\nreturn {{ prefillNewAutomationForm, automationCopyValues }};")();

        check("the checkbox is disabled", document.getElementById("automationMonitored").disabled, "enabled");
        check("and says why", holder.textContent.includes("Only admins can switch monitoring off or on."), holder.textContent);

        page.prefillNewAutomationForm(page.automationCopyValues(
            {{id: 7, name: "Experiment", type: "forecasting", "cron": "0 6 * * *", timezone: "UTC", monitored: false}},
            {{parameters: {{}}, source: {{id: 6}}}}));
        eq("a copy of an unmonitored automation is monitored", document.getElementById("automationMonitored").checked, true);
    """)
    assert_js(f"""
        const holder = document.createElement("div");
        holder.innerHTML = {json.dumps(creation_form_html(can_change_monitoring=True))};
        document.body.appendChild(holder);
        check("an admin's checkbox is enabled", !document.getElementById("automationMonitored").disabled, "disabled");
        check("and needs no explanation", !holder.textContent.includes("Only admins"), holder.textContent);
    """)


def test_the_monitoring_filter(assert_js):
    """The listing can be narrowed to monitored or unmonitored automations, and shows all of them by default."""
    assert_js(f"""
        window.$ = () => ({{ready: () => {{}}}});
        const page = new Function({json.dumps(copy_script())}
            + "\\nreturn {{ matchesMonitoringFilter, setFilter: (value) => {{ monitoringFilter = value; }} }};")();

        const monitored = {{id: 1, monitored: true}};
        const unmonitored = {{id: 2, monitored: false}};
        check("all are listed by default", page.matchesMonitoringFilter(monitored) && page.matchesMonitoringFilter(unmonitored), "");
        page.setFilter("monitored");
        check("monitored only keeps the monitored ones", page.matchesMonitoringFilter(monitored) && !page.matchesMonitoringFilter(unmonitored), "");
        page.setFilter("unmonitored");
        check("unmonitored only keeps the others", !page.matchesMonitoringFilter(monitored) && page.matchesMonitoringFilter(unmonitored), "");
    """)
