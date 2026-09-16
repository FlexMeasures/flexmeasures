"""Browser checks for the automation page's inline action controls."""

import json
import re
from pathlib import Path

import pytest
from jinja2 import Environment, StrictUndefined

TEMPLATE = (
    Path(__file__).resolve().parents[2] / "templates/assets/asset_automations.html"
)


@pytest.fixture(scope="module", autouse=True)
def setup_ui_test_data():
    """The inline-script checks do not need the UI suite's database fixtures."""


def automation_script(can_manage: bool, can_run: bool) -> str:
    """Render inline JavaScript with representative registered automation types."""
    template = TEMPLATE.read_text()
    match = re.search(r"<script>(.*?)</script>", template, re.DOTALL)
    assert match is not None
    return (
        Environment(autoescape=True, undefined=StrictUndefined)
        .from_string(match.group(1))
        .render(
            asset={"id": 3},
            user_can_manage_automations=can_manage,
            user_can_create_children=can_run,
            automation_types={
                "forecasting": "Forecasts",
                "scheduling": "Schedules",
                "mock-ingestion": "Mock ingestion",
            },
        )
    )


def test_automation_actions_are_grouped_and_permission_gated(assert_js):
    style_match = re.search(r"<style>(.*?)</style>", TEMPLATE.read_text(), re.DOTALL)
    assert style_match is not None
    manager_script = automation_script(can_manage=True, can_run=True)
    runner_script = automation_script(can_manage=False, can_run=True)
    viewer_script = automation_script(can_manage=False, can_run=False)
    assert_js(f"""
        // Keep the page's ready callback from trying to fetch data; exercise its row builder directly.
        const style = document.createElement("style");
        style.textContent = {json.dumps(style_match.group(1))};
        document.head.appendChild(style);
        window.$ = () => ({{ready: () => {{}}}});
        const manager = new Function({json.dumps(manager_script)} + "\\nreturn {{ AutomationRow }};")();
        const runner = new Function({json.dumps(runner_script)} + "\\nreturn {{ AutomationRow }};")();
        const viewer = new Function({json.dumps(viewer_script)} + "\\nreturn {{ AutomationRow }};")();
        const automation = {{
            id: 7, name: "Campus forecast", type: "forecasting", active: true,
            created_at: null, cronstr: "0 6 * * *", timezone: "Europe/Amsterdam",
            recurrence_description: "At 06:00", next_run: "2026-09-15T04:00:00+00:00",
        }};
        const row = manager.AutomationRow(automation);
        check("one menu holds all four controls", ["run-automation", "automation-edit", "automation-toggle", "automation-delete"]
              .every(name => row.actions.includes(name)), row.actions);
        check("run now is no longer mixed with details", !row.details.includes("run-automation"), row.details);
        check("details stays its own button", row.details.includes("automation-details"), row.details);
        const holder = document.createElement("div");
        holder.innerHTML = row.actions;
        document.body.appendChild(holder);
        const toggle = holder.querySelector(".automation-actions .dropdown-toggle");
        check("the row offers a single Actions toggle", toggle !== null
              && holder.querySelectorAll(".automation-actions > .btn").length === 1, row.actions);
        check("the four actions sit in its menu as items",
              holder.querySelectorAll(".automation-actions .dropdown-menu .dropdown-item").length === 4,
              row.actions);
        const inactive = manager.AutomationRow({{...automation, active: false, next_run: null}});
        check("inactive action says Activate", inactive.actions.includes("Activate") && !inactive.actions.includes("Deactivate"), inactive.actions);
        const runnerRow = runner.AutomationRow(automation);
        check("a viewer who may only run gets just that item",
              runnerRow.actions.includes("run-automation") && !runnerRow.actions.includes("automation-delete"),
              runnerRow.actions);
        const readonly = viewer.AutomationRow(automation);
        check("read-only view has no action items", !readonly.actions.includes("dropdown-item"), readonly.actions);
        """)


def test_action_menu_is_legible_over_the_theme(assert_js):
    """The theme paints .dropdown-menu dark but only recolours <a> links, so button items need their own rule."""
    style_match = re.search(r"<style>(.*?)</style>", TEMPLATE.read_text(), re.DOTALL)
    assert style_match is not None
    manager_script = automation_script(can_manage=True, can_run=True)
    assert_js(f"""
        // Reproduce the site rule that paints every dropdown menu in the navigation colours.
        const theme = document.createElement("style");
        theme.textContent = `:root {{ --nav-default-color: #fff; --nav-hover-color: #fff;
            --nav-default-background-color: #1a3443; --nav-hover-background-color: #33576b;
            --white: #fff; --delete-color: #c21431; }}
          .dropdown-menu {{ color: var(--nav-default-color); background-color: var(--nav-default-background-color); }}`;
        document.head.appendChild(theme);
        const style = document.createElement("style");
        style.textContent = {json.dumps(style_match.group(1))};
        document.head.appendChild(style);
        window.$ = () => ({{ready: () => {{}}}});
        const manager = new Function({json.dumps(manager_script)} + "\\nreturn {{ AutomationRow }};")();
        const holder = document.createElement("div");
        holder.innerHTML = manager.AutomationRow({{
            id: 7, name: "Campus forecast", type: "forecasting", active: true,
            created_at: null, cronstr: "0 6 * * *", timezone: "Europe/Amsterdam",
            recurrence_description: "At 06:00", next_run: "2026-09-15T04:00:00+00:00",
        }}).actions;
        document.body.appendChild(holder);
        const menu = holder.querySelector(".dropdown-menu");
        const parse = value => (value.match(/\\d+/g) || []).slice(0, 3).map(Number);
        const luminance = ([r, g, b]) => {{
            const channel = c => {{ c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }};
            return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
        }};
        const bg = parse(getComputedStyle(menu).backgroundColor);
        const items = [...menu.querySelectorAll(".dropdown-item")];
        const contrasts = items.map(item => {{
            const fg = parse(getComputedStyle(item).color);
            const [hi, lo] = [luminance(fg), luminance(bg)].sort((a, b) => b - a);
            return {{label: item.innerText.trim(), ratio: (hi + 0.05) / (lo + 0.05)}};
        }});
        check("every menu item is legible on the themed menu (AA, 4.5:1)",
              contrasts.every(c => c.ratio >= 4.5),
              contrasts.map(c => `${{c.label}} ${{c.ratio.toFixed(1)}}:1`).join(", "));
        """)


def test_a_name_with_an_apostrophe_survives_the_delete_confirmation(assert_js):
    """The name shown in the delete prompt is the one the automation carries.

    The row builder escapes the name into a data attribute, and the browser decodes
    character references while parsing, so reading the attribute back gives the original.
    """
    manager_script = automation_script(can_manage=True, can_run=True)
    assert_js(f"""
        window.$ = () => ({{ready: () => {{}}}});
        const manager = new Function({json.dumps(manager_script)} + "\\nreturn {{ AutomationRow }};")();
        const name = "Ronan's <b>day-ahead</b> & \\"nightly\\" forecast";
        const row = manager.AutomationRow({{
            id: 7, name, type: "forecasting", active: true,
            created_at: null, cronstr: "0 6 * * *", timezone: "Europe/Amsterdam",
            recurrence_description: "At 06:00", next_run: null,
        }});
        const holder = document.createElement("div");
        holder.innerHTML = row.actions;
        document.body.appendChild(holder);
        const del = holder.querySelector(".automation-delete");
        check("the delete control carries the name unescaped once read back",
              del.dataset.name === name, JSON.stringify(del.dataset.name));
        check("no character reference leaks into the name",
              !del.dataset.name.includes("&#") && !del.dataset.name.includes("&amp;"),
              JSON.stringify(del.dataset.name));
        check("the markup itself is escaped, so the name cannot inject elements",
              holder.querySelector("b") === null, row.actions);
        """)
