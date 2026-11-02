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
    assert_js(page_js("startNewAutomation, setNewAutomationDraft, prefillNewAutomationForm, automationCopyValues") + """
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
    """)
