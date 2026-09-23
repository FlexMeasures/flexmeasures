"""Browser checks for the data source picker in the automation page's creation modal."""

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


def picker_script() -> str:
    """Render the page's inline JavaScript, with the three Jinja values it reads filled in."""
    match = re.search(r"<script>(.*?)</script>", TEMPLATE.read_text(), re.DOTALL)
    assert match is not None
    return (
        match.group(1)
        .replace("{{ asset.id }}", "3")
        .replace("{{ user_can_manage_automations | tojson }}", "true")
        .replace("{{ user_can_create_children | tojson }}", "true")
    )


def test_source_search_asks_for_the_sources_of_the_automations_own_type(assert_js):
    """A forecast automation searches forecasters, a report automation reporters, and a schedule automation has no generator to pick."""
    assert_js(f"""
        window.$ = () => ({{ready: () => {{}}}});
        const page = new Function({json.dumps(picker_script())}
            + "\\nreturn {{ sourceSearchUrl, sourceLabel, sourceResultsHtml, sourceConfigText }};")();

        const forecastUrl = new URL(page.sourceSearchUrl("forecasting", "pipeline"), "http://x");
        eq("a forecast automation searches forecasters", forecastUrl.searchParams.get("type"), "forecaster");
        eq("the search term is passed on", forecastUrl.searchParams.get("filter"), "pipeline");
        eq("every version can be picked, not just the latest", forecastUrl.searchParams.get("only_latest"), "false");

        const reportUrl = new URL(page.sourceSearchUrl("reporting", ""), "http://x");
        eq("a report automation searches reporters", reportUrl.searchParams.get("type"), "reporter");
        eq("an empty search term is left out", reportUrl.searchParams.get("filter"), null);

        const scheduleUrl = new URL(page.sourceSearchUrl("scheduling", "x"), "http://x");
        eq("a schedule automation narrows to no source type", scheduleUrl.searchParams.get("type"), null);
    """)


def test_search_results_name_each_source_and_cap_a_broad_search(assert_js):
    """Each result carries the id the picker reads the source by, and a long list says how much it leaves out."""
    assert_js(f"""
        window.$ = () => ({{ready: () => {{}}}});
        const page = new Function({json.dumps(picker_script())}
            + "\\nreturn {{ sourceSearchUrl, sourceLabel, sourceResultsHtml, sourceConfigText, MAX_SOURCE_RESULTS }};")();

        eq("a source is named by its description and its id",
           page.sourceLabel({{id: 6, name: "Seita", description: "Seita's TrainPredictPipeline model v1"}}),
           "Seita's TrainPredictPipeline model v1 (data source 6)");
        eq("a source without a description falls back to its name",
           page.sourceLabel({{id: 7, name: "Seita"}}), "Seita (data source 7)");

        const empty = page.sourceResultsHtml([]);
        check("an empty search says so rather than showing nothing", empty.includes("No matching data sources"), empty);

        const one = page.sourceResultsHtml([{{id: 6, name: "Seita", description: "Seita's forecaster"}}]);
        check("a result carries the id the picker reads the source by", one.includes('data-source-id="6"'), one);
        check("a result is a button, so it cannot submit the form", one.includes('type="button"'), one);

        const many = Array.from({{length: page.MAX_SOURCE_RESULTS + 3}}, (_, i) => ({{id: i + 1, name: "Seita"}}));
        const capped = page.sourceResultsHtml(many);
        eq("a broad search shows at most the cap",
           (capped.match(/automation-source-option/g) || []).length, page.MAX_SOURCE_RESULTS);
        check("and says how many it leaves out", capped.includes("3 more match"), capped);

        const hostile = page.sourceResultsHtml([{{id: 1, name: "<img src=x onerror=alert(1)>"}}]);
        check("a source name is escaped rather than rendered", !hostile.includes("<img"), hostile);
    """)


def test_the_selected_sources_configuration_is_shown_as_it_is_stored(assert_js):
    """The picker shows the config the data generator stores on the source, which is what the automation would run under."""
    assert_js(f"""
        window.$ = () => ({{ready: () => {{}}}});
        const page = new Function({json.dumps(picker_script())}
            + "\\nreturn {{ sourceConfigText }};")();

        eq("the stored config is shown as it is stored",
           page.sourceConfigText({{attributes: {{data_generator: {{config: {{model: "CustomLGBM"}}}}}}}}),
           JSON.stringify({{model: "CustomLGBM"}}, null, 4));
        const none = page.sourceConfigText({{attributes: {{}}}});
        check("a source storing no config says so", none.includes("no data generator configuration"), none);
        const bare = page.sourceConfigText({{}});
        check("and so does a source with no attributes at all", bare.includes("no data generator configuration"), bare);
    """)
