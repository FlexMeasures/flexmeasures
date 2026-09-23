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


def automation_script(
    can_manage: bool,
    can_run: bool,
    has_children: bool = False,
    include_children: bool = True,
) -> str:
    """Render the Jinja values used by the page's inline JavaScript."""
    template = TEMPLATE.read_text()
    match = re.search(r"<script>(.*?)</script>", template, re.DOTALL)
    assert match is not None
    script = (
        match.group(1)
        .replace("{{ asset.id }}", "3")
        .replace("{{ user_can_manage_automations | tojson }}", str(can_manage).lower())
        .replace("{{ user_can_create_children | tojson }}", str(can_run).lower())
        .replace(
            "{{ 'true' if include_child_assets else 'false' }}",
            str(include_children).lower(),
        )
        .replace(
            "{{ 'true' if asset.child_assets else 'false' }}", str(has_children).lower()
        )
    )
    # An unrendered value would reach the browser as a syntax error, which reads as every check failing at once.
    assert (
        "{{" not in script
    ), "this helper does not render every Jinja value the page's script uses"
    return script


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
        check("run now is no longer mixed with info", !row.info.includes("run-automation"), row.info);
        check("info stays its own button", row.info.includes("automation-info"), row.info);
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


# The page's row builder calls the shared time helper, which lives in a classic script
# rather than a module, so it is loaded here the way the page itself loads it.
LOAD_TIME_HELPERS = """
    // The real page loads jQuery and the charting libraries first, and the helper file
    // reaches for all three as it runs. A chainable no-op stands in for whatever it touches.
    const noop = new Proxy(function () {}, {get: () => noop, apply: () => noop});
    window.$ = noop;
    window.jQuery = noop;
    window.vega = noop;
    window.d3 = noop;
    await new Promise((resolve, reject) => {
        const tag = document.createElement("script");
        tag.src = "/js/flexmeasures.js";
        tag.onload = resolve;
        tag.onerror = () => reject(new Error("could not load flexmeasures.js"));
        document.head.appendChild(tag);
    });
    check("the shared time helper is loaded", typeof getHumanFriendlyDeltaOrTimeStr === "function");
"""


def test_the_next_run_reads_as_a_delta_with_the_clock_time_on_hover(assert_js):
    """Review of #2294: say "in 6 minutes" rather than a date, and keep the precise time on hover."""
    manager_script = automation_script(can_manage=True, can_run=True)
    assert_js(f"""
        {LOAD_TIME_HELPERS}
        const manager = new Function({json.dumps(manager_script)} + "\\nreturn {{ AutomationRow }};")();
        // Half a minute past six, so that the helper's rounding down still lands on six.
        const soon = new Date(Date.now() + 6.5 * 60 * 1000).toISOString();
        const automation = {{
            id: 7, name: "Campus forecast", type: "forecasting", active: true, asset: 3,
            "created-at": null, cron: "0 6 * * *", timezone: "Europe/Amsterdam",
            "recurrence-description": "At 06:00", "next-run": soon,
        }};
        const cell = manager.AutomationRow(automation)["next-run"].display;
        const holder = document.createElement("div");
        holder.innerHTML = cell;
        const span = holder.querySelector("span");
        check("a run six minutes off is said to be in six minutes",
              span.textContent.trim() === "in 6 minutes", span.textContent);
        check("the precise time waits on hover", /\\d{{2}} \\w+ \\d{{4}}, \\d{{2}}:\\d{{2}}/.test(span.title), span.title);
        check("the hover names the clock the time is read on",
              span.title.startsWith("Europe/Amsterdam:"), span.title);
        check("the hover also carries the recurrence", span.title.includes("0 6 * * *"), span.title);

        // Beyond a week there is no useful delta left, so the cell falls back to the schedule's own clock.
        const distant = new Date(Date.now() + 40 * 24 * 3600 * 1000).toISOString();
        const far = manager.AutomationRow({{...automation, "next-run": distant}})["next-run"].display;
        const farSpan = Object.assign(document.createElement("div"), {{innerHTML: far}}).querySelector("span");
        check("a distant run is dated rather than described",
              /\\d{{2}} \\w+ \\d{{4}}/.test(farSpan.textContent), farSpan.textContent);
        check("and it is dated on the automation's clock, not the viewer's",
              farSpan.textContent.trim() === farSpan.title.replace("Europe/Amsterdam: ", "").replace(" (0 6 * * *)", ""),
              `${{farSpan.textContent}} vs ${{farSpan.title}}`);

        // Sorting still runs on the moment itself, not on the words shown.
        const order = manager.AutomationRow(automation)["next-run"].order;
        check("the column still sorts on the moment", order === new Date(soon).getTime(), String(order));
        """)


def test_created_at_is_read_on_the_automations_own_clock(assert_js):
    manager_script = automation_script(can_manage=True, can_run=True)
    assert_js(f"""
        {LOAD_TIME_HELPERS}
        const manager = new Function({json.dumps(manager_script)} + "\\nreturn {{ AutomationRow }};")();
        // A moment that falls on a different date in Auckland than it does in UTC.
        const created = "2026-07-11T22:00:00+00:00";
        const cell = manager.AutomationRow({{
            id: 7, name: "Campus forecast", type: "forecasting", active: true, asset: 3,
            "created-at": created, cron: "0 6 * * *", timezone: "Pacific/Auckland",
            "recurrence-description": "At 06:00", "next-run": null,
        }})["created-at"].display;
        const span = Object.assign(document.createElement("div"), {{innerHTML: cell}}).querySelector("span");
        check("the hover names the automation's timezone",
              span.title.startsWith("Pacific/Auckland:"), span.title);
        check("the hover reads the moment on that clock, a day later than in UTC",
              span.title.includes("12 Jul 2026") && span.title.includes("10:00"), span.title);
        check("the raw stored timestamp is no longer what hovering shows",
              !span.title.includes("T22:00:00"), span.title);
        """)


def test_the_asset_column_appears_only_when_the_listing_spans_several_assets(assert_js):
    """An asset's own listing needs no Asset column; one that reaches below it does."""
    spanning = automation_script(
        can_manage=True, can_run=True, has_children=True, include_children=True
    )
    narrowed = automation_script(
        can_manage=True, can_run=True, has_children=True, include_children=False
    )
    childless = automation_script(
        can_manage=True, can_run=True, has_children=False, include_children=True
    )
    assert_js(f"""
        {LOAD_TIME_HELPERS}
        const automation = {{
            id: 7, name: "Campus forecast", type: "forecasting", active: true, asset: 4,
            "asset-name": "Rooftop PV", "created-at": null, cron: "0 6 * * *",
            timezone: "Europe/Amsterdam", "recurrence-description": "At 06:00", "next-run": null,
        }};
        const rowOf = (script) => new Function(script + "\\nreturn {{ AutomationRow }};")().AutomationRow(automation);
        const spanning = rowOf({json.dumps(spanning)});
        check("the row names the asset the automation is defined on",
              spanning["asset-name"].includes("Rooftop PV"), spanning["asset-name"]);
        check("and links to that asset's own automations page",
              spanning["asset-name"].includes('href="/assets/4/automations"'), spanning["asset-name"]);
        """)
    # The column set itself is decided in makeAutomationsTable, which reads the same two flags.
    for label, script, expected in [
        ("spanning", spanning, True),
        ("narrowed", narrowed, False),
        ("childless", childless, False),
    ]:
        shows_column = (
            'assetHasChildren && includeChildAssets ? [{ data: "asset-name", title: "Asset" }]'
            in script
        )
        assert shows_column, "the column is still chosen by those two flags"
        wants = ("let includeChildAssets = true" in script) and (
            "const assetHasChildren = true" in script
        )
        assert (
            wants is expected
        ), f"{label} should{'' if expected else ' not'} span several assets"
