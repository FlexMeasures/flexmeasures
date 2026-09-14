"""Browser checks for the automation page's inline action controls."""

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


def automation_script(can_manage: bool, can_run: bool) -> str:
    """Render the three Jinja values used by the page's inline JavaScript."""
    template = TEMPLATE.read_text()
    match = re.search(r"<script>(.*?)</script>", template, re.DOTALL)
    assert match is not None
    return (
        match.group(1)
        .replace("{{ asset.id }}", "3")
        .replace("{{ user_can_manage_automations | tojson }}", str(can_manage).lower())
        .replace("{{ user_can_create_children | tojson }}", str(can_run).lower())
    )


def test_automation_actions_are_grouped_and_permission_gated(assert_js):
    style_match = re.search(r"<style>(.*?)</style>", TEMPLATE.read_text(), re.DOTALL)
    assert style_match is not None
    manager_script = automation_script(can_manage=True, can_run=True)
    viewer_script = automation_script(can_manage=False, can_run=False)
    assert_js(f"""
        // Keep the page's ready callback from trying to fetch data; exercise its row builder directly.
        const style = document.createElement("style");
        style.textContent = {json.dumps(style_match.group(1))};
        document.head.appendChild(style);
        window.$ = () => ({{ready: () => {{}}}});
        const manager = new Function({json.dumps(manager_script)} + "\\nreturn {{ AutomationRow }};")();
        const viewer = new Function({json.dumps(viewer_script)} + "\\nreturn {{ AutomationRow }};")();
        const automation = {{
            id: 7, name: "Campus forecast", type: "forecasting", active: true,
            created_at: null, cronstr: "0 6 * * *", timezone: "Europe/Amsterdam",
            recurrence_description: "At 06:00", next_run: "2026-09-15T04:00:00+00:00",
        }};
        const row = manager.AutomationRow(automation);
        check("one action group holds all four controls", ["run-automation", "automation-edit", "automation-toggle", "automation-delete"]
              .every(name => row.actions.includes(name)), row.actions);
        check("run now is no longer mixed with details", !row.details.includes("run-automation"), row.details);
        const holder = document.createElement("div");
        holder.innerHTML = row.actions;
        document.body.appendChild(holder);
        const group = holder.querySelector(".automation-actions");
        const buttons = [...group.querySelectorAll("button")];
        check("actions form a centered two-column grid", getComputedStyle(group).display === "grid"
              && getComputedStyle(group).justifyContent === "center"
              && buttons.length === 4
              && Math.abs(buttons[0].getBoundingClientRect().top - buttons[1].getBoundingClientRect().top) < 1
              && Math.abs(buttons[2].getBoundingClientRect().top - buttons[3].getBoundingClientRect().top) < 1
              && buttons[2].getBoundingClientRect().top > buttons[0].getBoundingClientRect().top,
              row.actions);
        const inactive = manager.AutomationRow({{...automation, active: false, next_run: null}});
        check("inactive action says Activate", inactive.actions.includes("Activate") && !inactive.actions.includes("Deactivate"), inactive.actions);
        const readonly = viewer.AutomationRow(automation);
        check("read-only view has no action buttons", !readonly.actions.includes("<button"), readonly.actions);
        """)


def test_action_buttons_line_up_across_rows(assert_js):
    """A row whose toggle reads "Activate" must not sit out of line with rows reading "Deactivate"."""
    style_match = re.search(r"<style>(.*?)</style>", TEMPLATE.read_text(), re.DOTALL)
    assert style_match is not None
    manager_script = automation_script(can_manage=True, can_run=True)
    assert_js(f"""
        const style = document.createElement("style");
        style.textContent = {json.dumps(style_match.group(1))};
        document.head.appendChild(style);
        window.$ = () => ({{ready: () => {{}}}});
        const manager = new Function({json.dumps(manager_script)} + "\\nreturn {{ AutomationRow }};")();
        const automation = {{
            id: 7, name: "Campus forecast", type: "forecasting", active: true,
            created_at: null, cronstr: "0 6 * * *", timezone: "Europe/Amsterdam",
            recurrence_description: "At 06:00", next_run: "2026-09-15T04:00:00+00:00",
        }};
        // Build the two rows in one table cell each, the way the listing stacks them.
        const table = document.createElement("table");
        table.style.width = "600px";
        table.innerHTML = `<tbody>
            <tr><td class="text-center align-middle">${{manager.AutomationRow(automation).actions}}</td></tr>
            <tr><td class="text-center align-middle">${{manager.AutomationRow({{...automation, active: false, next_run: null}}).actions}}</td></tr>
        </tbody>`;
        document.body.appendChild(table);
        const [activeRow, inactiveRow] = [...table.querySelectorAll(".automation-actions")];
        const lefts = group => [...group.querySelectorAll("button")].map(b => Math.round(b.getBoundingClientRect().left));
        const widths = group => [...group.querySelectorAll("button")].map(b => Math.round(b.getBoundingClientRect().width));
        check("the shorter Activate label does not shift the group",
              JSON.stringify(lefts(activeRow)) === JSON.stringify(lefts(inactiveRow)),
              `Deactivate row lefts ${{lefts(activeRow)}} vs Activate row lefts ${{lefts(inactiveRow)}}`);
        check("every button in a group shares one width",
              new Set([...widths(activeRow), ...widths(inactiveRow)]).size === 1,
              `widths ${{widths(activeRow)}} and ${{widths(inactiveRow)}}`);
        """)
