"""Browser checks for opening the automation page's creation form from the New automation button."""

import json

import pytest

from test_automation_actions import automation_script
from test_automation_copy import JQUERY_STUB, creation_form_html


@pytest.fixture(scope="module", autouse=True)
def setup_ui_test_data():
    """The inline-script checks do not need the UI suite's database fixtures."""


# The type tabs as the page renders them, with the Reporting tab in front.
TABS_HTML = """
    <ul class="nav nav-tabs">
      <li><button class="nav-link" id="forecasting-tab"></button></li>
      <li><button class="nav-link" id="scheduling-tab"></button></li>
      <li><button class="nav-link active" id="reporting-tab"></button></li>
      <li><button class="nav-link" id="my-plugin-type-tab"></button></li>
    </ul>
"""


def page_js(functions: str) -> str:
    """Put the creation form and the type tabs on the page, and expose the named functions of the page's script."""
    script = automation_script(can_manage=True, can_run=True)
    return f"""
        const holder = document.createElement("div");
        holder.innerHTML = {json.dumps(TABS_HTML + creation_form_html())};
        document.body.appendChild(holder);
        {JQUERY_STUB}
        const page = new Function({json.dumps(script)} + "\\nreturn {{ {functions} }};")();
        const field = (id) => document.getElementById(id);
        const activate = (type) => document.querySelectorAll(".nav-link").forEach(
            tab => tab.classList.toggle("active", tab.id === `${{type}}-tab`));
    """


def test_a_new_automation_takes_the_type_of_the_tab_in_front(assert_js):
    """New automation on the Reporting tab starts a report, with a report's examples."""
    assert_js(page_js("startNewAutomation") + """
        page.startNewAutomation();
        eq("the type is the Reporting tab's", field("automationType").value, "reporting");
        eq("with a reporter as the example generator",
           field("automationGenerator").getAttribute("placeholder"), "PandasReporter");

        activate("scheduling");
        page.startNewAutomation();
        eq("on the Scheduling tab, a schedule", field("automationType").value, "scheduling");

        activate("my-plugin-type");
        page.startNewAutomation();
        eq("a plugin type's tab cannot be created from the form, so the form's default type is kept",
           field("automationType").value, "forecasting");
    """)


def test_a_draft_is_kept_until_cleared(assert_js):
    """Typing into the form makes a draft, which is shown with a way to clear it; emptying the form ends it."""
    assert_js(
        page_js(
            "startNewAutomation, setNewAutomationDraft, prefillNewAutomationForm, automationCopyValues"
        )
        + """
        page.startNewAutomation();
        check("a blank form offers nothing to clear", field("newAutomationClear").classList.contains("d-none"), "shown");

        page.setNewAutomationDraft(true);
        check("a draft can be cleared", !field("newAutomationClear").classList.contains("d-none"), "hidden");

        page.startNewAutomation();
        check("starting afresh ends the draft", field("newAutomationClear").classList.contains("d-none"), "still shown");

        // A copy is filled in by the page, not typed, so it is not a draft until something in it is changed.
        page.setNewAutomationDraft(true);
        page.prefillNewAutomationForm(page.automationCopyValues(
            {id: 7, name: "Campus forecast", type: "forecasting", "cron": "0 6 * * *", timezone: "UTC"},
            {parameters: {}, source: {id: 6}}));
        check("a copy is not a draft", field("newAutomationClear").classList.contains("d-none"), "shown");
    """
    )


# The clipped-values template as the API describes it, with two value placeholders and two sensor placeholders.
CLIPPED_VALUES = {
    "name": "clipped-values",
    "description": "Sensor values clipped to a valid range.",
    "reporter": "PandasReporter",
    "config": {
        "transformations": [
            {"method": "clip", "kwargs": {"lower": "FILL_IN", "upper": "FILL_IN"}}
        ]
    },
    "parameters": {
        "input": [{"name": "measurements", "sensor": "FILL_IN"}],
        "output": [{"name": "clipped", "sensor": "FILL_IN"}],
        "start-offset": "-1D,DB",
        "end-offset": "DB",
    },
    "placeholders": [
        {
            "section": "config",
            "location": ["transformations", 0, "kwargs", "lower"],
            "kind": "value",
            "label": "Lower",
        },
        {
            "section": "config",
            "location": ["transformations", 0, "kwargs", "upper"],
            "kind": "value",
            "label": "Upper",
        },
        {
            "section": "parameters",
            "location": ["input", 0, "sensor"],
            "kind": "sensor",
            "label": "Input sensor: measurements",
        },
        {
            "section": "parameters",
            "location": ["output", 0, "sensor"],
            "kind": "sensor",
            "label": "Output sensor: clipped",
        },
    ],
}


def test_a_template_and_its_fields_add_up_to_a_report_definition(assert_js):
    """Each field fills its placeholder, numbers stay numbers, the window can be edited, and an empty field is named."""
    assert_js(
        page_js(
            "startNewAutomation, showTemplateFields, filledInTemplate, reportTemplatesByName"
        )
        + f"""
        const template = {json.dumps(CLIPPED_VALUES)};
        page.reportTemplatesByName.set(template.name, template);
        page.startNewAutomation();
        const option = document.createElement("option");
        option.value = template.name;
        field("automationTemplate").appendChild(option);
        field("automationTemplate").value = template.name;
        page.showTemplateFields();

        eq("the name is taken from the template", field("automationName").value, "Clipped values");
        eq("the window is pre-filled", field("automationTemplateStartOffset").value, "-1D,DB");
        check("the hand-written parameters are hidden", field("automationParametersField").style.display === "none", "shown");

        field("automationTemplatePlaceholder-0").value = "0";
        field("automationTemplatePlaceholder-2").dataset.sensorId = "37";
        let refusal = null;
        try {{ page.filledInTemplate(template); }} catch (error) {{ refusal = error.message; }}
        check("an empty field is refused by its label",
              refusal !== null && refusal.includes("Upper") && refusal.includes("Output sensor: clipped") && !refusal.includes("Lower"), refusal);

        const draft = page.filledInTemplate(template, {{allowUnfilled: true}});
        eq("allowing unfilled fields keeps their placeholders", draft.config.transformations[0].kwargs.upper, "FILL_IN");

        field("automationTemplatePlaceholder-1").value = "15.5";
        field("automationTemplatePlaceholder-3").dataset.sensorId = "45";
        field("automationTemplateEndOffset").value = "";
        const definition = page.filledInTemplate(template);
        eq("the bounds become numbers", definition.config.transformations[0].kwargs, {{lower: 0, upper: 15.5}});
        eq("the sensors become IDs", [definition.parameters.input[0].sensor, definition.parameters.output[0].sensor], [37, 45]);
        eq("the edited window is used", definition.parameters["start-offset"], "-1D,DB");
        check("and a cleared offset is left out", !("end-offset" in definition.parameters), JSON.stringify(definition.parameters));
        eq("the template itself is left as it was", template.parameters.input[0].sensor, "FILL_IN");
    """
    )
