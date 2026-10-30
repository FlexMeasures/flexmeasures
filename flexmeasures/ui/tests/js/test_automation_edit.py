"""Browser checks for editing an automation's parameters and config on the automation page."""

import json
import re

import pytest

from test_automation_actions import TEMPLATE, automation_script
from test_automation_copy import JQUERY_STUB


@pytest.fixture(scope="module", autouse=True)
def setup_ui_test_data():
    """The inline-script checks do not need the UI suite's database fixtures."""


def edit_form_html() -> str:
    """The edit form as the page renders it, so the checks run against the real fields."""
    match = re.search(
        r'(<form id="editAutomationForm">.*?</form>)', TEMPLATE.read_text(), re.DOTALL
    )
    assert match is not None
    return match.group(1)


def edit_page_js(checks: str) -> str:
    """Put the edit form on the page, load the page's script, and run the given checks against both."""
    script = automation_script(can_manage=True, can_run=True)
    return f"""
        // Appended rather than assigned to the body, which holds the harness's own results element.
        const holder = document.createElement("div");
        holder.innerHTML = {json.dumps(edit_form_html())};
        document.body.appendChild(holder);
        {JQUERY_STUB}
        const page = new Function({json.dumps(script)}
            + "\\nreturn {{ loadedEditDefinition, fillEditAutomationDefinition, resetEditAutomationDefinition, editedDefinition }};")();
        const field = (id) => document.getElementById(id);
        {checks}
    """


def test_the_edit_form_sends_only_the_parameters_and_config_that_changed(assert_js):
    """An unchanged field is left out, so that a rename does not check stored parameters again."""
    assert_js(edit_page_js("""
        const loaded = page.loadedEditDefinition(
            {id: 7, type: "forecasting"},
            {parameters: {sensor: 2092, "start-offset": "1D,DB"},
             source: {id: 6, description: "TrainPredictPipeline", config: {"train-period": "P30D"}}});
        page.fillEditAutomationDefinition(loaded);

        eq("the parameters are filled in as stored", JSON.parse(field("editAutomationParameters").value),
           {sensor: 2092, "start-offset": "1D,DB"});
        eq("and so is the config", JSON.parse(field("editAutomationConfig").value), {"train-period": "P30D"});
        check("both can be edited once loaded",
              !field("editAutomationParameters").disabled && !field("editAutomationConfig").disabled, "still disabled");
        check("the config is shown for a forecast automation",
              !field("editAutomationConfigGroup").classList.contains("d-none"), "hidden");
        check("and says which data source it is stored on", field("editAutomationGenerator").textContent.includes("6"),
              field("editAutomationGenerator").textContent);

        eq("nothing changed, so neither is sent", page.editedDefinition(loaded), {});

        field("editAutomationParameters").value = JSON.stringify({sensor: 2093, "start-offset": "1D,DB"});
        eq("changed parameters are sent on their own", page.editedDefinition(loaded),
           {parameters: {sensor: 2093, "start-offset": "1D,DB"}});

        page.fillEditAutomationDefinition(loaded);
        field("editAutomationConfig").value = '{"train-period": "P60D"}';
        eq("a changed config is sent on its own", page.editedDefinition(loaded), {config: {"train-period": "P60D"}});

        field("editAutomationConfig").value = "{not json";
        let error = null;
        try { page.editedDefinition(loaded); } catch (e) { error = e.message; }
        check("malformed JSON is reported against its field", error !== null && error.startsWith("Data generator config"), error);
    """))


def test_the_edit_form_takes_over_the_runs_only_when_asked(assert_js):
    """Run-as-me is sent only when ticked, so that an edit keeps the user whom the automation runs as by default."""
    assert_js(edit_page_js("""
        page.resetEditAutomationDefinition();
        check("run-as-me waits for the automation to load", field("editAutomationRunAsMe").disabled, "enabled");
        const loaded = page.loadedEditDefinition(
            {id: 7, type: "forecasting"},
            {parameters: {sensor: 2092}, source: {id: 6, description: "TrainPredictPipeline", config: {}}});
        page.fillEditAutomationDefinition(loaded);
        check("and can be ticked once it has", !field("editAutomationRunAsMe").disabled, "disabled");

        eq("unticked, it is not sent", page.editedDefinition(loaded), {});
        field("editAutomationRunAsMe").checked = true;
        eq("ticked, it is sent, also without other changes", page.editedDefinition(loaded), {"run-as-me": true});
        field("editAutomationParameters").value = JSON.stringify({sensor: 2093});
        eq("and together with them", page.editedDefinition(loaded), {parameters: {sensor: 2093}, "run-as-me": true});

        page.resetEditAutomationDefinition();
        check("reopening the form unticks it", !field("editAutomationRunAsMe").checked, "still ticked");
    """))


def test_a_schedule_automation_offers_no_config_to_edit(assert_js):
    """A schedule automation's data source follows from the asset, so the form hides the config and never sends one."""
    assert_js(edit_page_js("""
        page.resetEditAutomationDefinition();
        const loaded = page.loadedEditDefinition(
            {id: 8, type: "scheduling"},
            {parameters: {duration: "PT12H"}, source: {id: 9, description: "StorageScheduler", config: {asset: 3}}});
        page.fillEditAutomationDefinition(loaded);

        eq("no config is loaded", loaded.config, null);
        check("the config field stays hidden", field("editAutomationConfigGroup").classList.contains("d-none"), "shown");
        check("the parameters can be edited", !field("editAutomationParameters").disabled, "disabled");
        field("editAutomationParameters").value = '{"duration": "PT24H"}';
        eq("only the parameters are sent", page.editedDefinition(loaded), {parameters: {duration: "PT24H"}});
    """))


def test_reopening_the_edit_form_starts_from_a_clean_slate(assert_js):
    """The form is shared between automations, so what one left in it must not be sent for the next while it loads."""
    assert_js(edit_page_js("""
        page.fillEditAutomationDefinition(page.loadedEditDefinition(
            {id: 7, type: "reporting"}, {parameters: {sensor: 1}, source: {id: 6, description: "PandasReporter", config: {}}}));
        page.resetEditAutomationDefinition();

        eq("the parameters are cleared", field("editAutomationParameters").value, "");
        eq("and the config", field("editAutomationConfig").value, "");
        check("and both are disabled until the next automation is loaded",
              field("editAutomationParameters").disabled && field("editAutomationConfig").disabled, "enabled");
        check("and the config is hidden again", field("editAutomationConfigGroup").classList.contains("d-none"), "shown");
    """))
