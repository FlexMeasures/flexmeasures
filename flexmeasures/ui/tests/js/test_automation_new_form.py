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
    """Each field fills its placeholder, numbers stay numbers, the window can be edited but not left out, and an empty or non-numeric field is named."""
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
        const other = {{...template, name: "valid-range"}};
        page.reportTemplatesByName.set(other.name, other);
        const otherOption = document.createElement("option");
        otherOption.value = other.name;
        field("automationTemplate").appendChild(otherOption);
        field("automationTemplate").value = other.name;
        page.showTemplateFields();
        eq("a name taken from a template follows the next template chosen", field("automationName").value, "Valid range");
        field("automationName").value = "My own name";
        field("automationTemplate").value = template.name;
        page.showTemplateFields();
        eq("a typed name stays", field("automationName").value, "My own name");
        field("automationName").value = "";
        page.showTemplateFields();
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

        field("automationTemplatePlaceholder-1").value = "abc";
        field("automationTemplatePlaceholder-3").dataset.sensorId = "45";
        refusal = null;
        try {{ page.filledInTemplate(template); }} catch (error) {{ refusal = error.message; }}
        check("text in place of a number is refused by its label", refusal !== null && refusal.includes("number") && refusal.includes("Upper"), refusal);

        field("automationTemplatePlaceholder-1").value = "15,5";
        field("automationTemplateEndOffset").value = "";
        refusal = null;
        try {{ page.filledInTemplate(template); }} catch (error) {{ refusal = error.message; }}
        check("a cleared offset is refused by its label", refusal !== null && refusal.includes("End offset"), refusal);

        field("automationTemplateEndOffset").value = "DB,1h";
        const definition = page.filledInTemplate(template);
        eq("the bounds become numbers, reading a decimal comma as a point", definition.config.transformations[0].kwargs, {{lower: 0, upper: 15.5}});
        eq("the sensors become IDs", [definition.parameters.input[0].sensor, definition.parameters.output[0].sensor], [37, 45]);
        eq("the edited window is used", [definition.parameters["start-offset"], definition.parameters["end-offset"]], ["-1D,DB", "DB,1h"]);
        eq("the template itself is left as it was", template.parameters.input[0].sensor, "FILL_IN");
    """
    )


# The aggregate-sensors template as the API describes it, which lets inputs be added and weighed.
AGGREGATE_SENSORS = {
    "name": "aggregate-sensors",
    "description": "Aggregate several sensors.",
    "reporter": "AggregatorReporter",
    "form": {"add_inputs": "part", "input_weights": True},
    "config": {"method": "sum"},
    "parameters": {
        "input": [
            {"name": "part-1", "sensor": "FILL_IN"},
            {"name": "part-2", "sensor": "FILL_IN"},
        ],
        "output": [{"sensor": "FILL_IN"}],
        "start-offset": "-1D,DB",
        "end-offset": "DB",
    },
    "placeholders": [
        {
            "section": "parameters",
            "location": ["input", 0, "sensor"],
            "kind": "sensor",
            "label": "Input sensor: part-1",
        },
        {
            "section": "parameters",
            "location": ["input", 1, "sensor"],
            "kind": "sensor",
            "label": "Input sensor: part-2",
        },
        {
            "section": "parameters",
            "location": ["output", 0, "sensor"],
            "kind": "sensor",
            "label": "Output sensor",
        },
    ],
}


def test_inputs_can_be_added_to_a_sum_and_weighed(assert_js):
    """More sensors can be added to a sum, each before the output, and a weight of -1 subtracts one."""
    assert_js(
        page_js(
            "startNewAutomation, showTemplateFields, addTemplateInput, removeTemplateInput, filledInTemplate, selectedReportTemplate, reportTemplatesByName"
        )
        + f"""
        const loaded = {json.dumps(AGGREGATE_SENSORS)};
        page.reportTemplatesByName.set(loaded.name, loaded);
        page.startNewAutomation();
        const option = document.createElement("option");
        option.value = loaded.name;
        field("automationTemplate").appendChild(option);
        field("automationTemplate").value = loaded.name;
        page.showTemplateFields();

        const labels = () => [...document.querySelectorAll("#automationTemplateFields label")].map(label => label.textContent);
        eq("each input gets a weight", document.querySelectorAll(".template-weight").length, 2);

        page.addTemplateInput();
        page.addTemplateInput();
        eq("added inputs go before the output",
           labels(), ["Input sensor: part-1", "Input sensor: part-2", "Input sensor: part-3", "Input sensor: part-4", "Output sensor"]);
        page.removeTemplateInput();
        eq("the last added input can be removed again",
           labels(), ["Input sensor: part-1", "Input sensor: part-2", "Input sensor: part-3", "Output sensor"]);

        const template = page.selectedReportTemplate();
        // The placeholders keep their order, so the output's field is the third and the added input's the fourth.
        field("automationTemplatePlaceholder-0").dataset.sensorId = "11";
        field("automationTemplatePlaceholder-1").dataset.sensorId = "12";
        field("automationTemplatePlaceholder-2").dataset.sensorId = "20";
        field("automationTemplatePlaceholder-3").dataset.sensorId = "13";
        document.querySelector('.template-weight[data-input-name="part-3"]').value = "-1";
        const definition = page.filledInTemplate(template);

        eq("the added input is read", definition.parameters.input,
           [{{name: "part-1", sensor: 11}}, {{name: "part-2", sensor: 12}}, {{name: "part-3", sensor: 13}}]);
        eq("the output is still the output", definition.parameters.output, [{{sensor: 20}}]);
        eq("only a weight other than 1 is stored", definition.config.weights, {{"part-3": -1}});
        eq("the template as loaded is left as it was", loaded.parameters.input.length, 2);

        page.showTemplateFields();
        eq("choosing the template again starts from its own inputs", labels().length, 3);
    """
    )


def test_the_template_list_reads_as_words_with_a_summary_on_hover(assert_js):
    """A template is listed by its name without hyphens, with its short summary as the hover text."""
    assert_js(
        page_js("templateChoiceHtml, templateChoiceLabel, reportTemplatesByName") + f"""
        const template = {json.dumps(dict(CLIPPED_VALUES, form={"summary": "Caps a sensor's values to a range."}))};
        const list = document.createElement("ul");
        list.innerHTML = page.templateChoiceHtml(template);
        const choice = list.querySelector(".template-choice");
        eq("the name reads as words", choice.textContent, "Clipped values");
        eq("the summary shows on hover", choice.getAttribute("title"), "Caps a sensor's values to a range.");
        eq("choosing it sets the template", choice.dataset.template, "clipped-values");

        const without = {json.dumps(CLIPPED_VALUES)};
        list.innerHTML = page.templateChoiceHtml(without);
        eq("without a summary, the description shows instead",
           list.querySelector(".template-choice").getAttribute("title"), without.description);

        page.reportTemplatesByName.set(template.name, template);
        eq("the list's button names the chosen template", page.templateChoiceLabel("clipped-values"), "Clipped values");
        eq("or says that none is chosen", page.templateChoiceLabel(""), "None: write the report definition myself");
    """
    )
