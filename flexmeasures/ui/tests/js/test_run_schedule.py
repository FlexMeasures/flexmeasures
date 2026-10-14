"""Browser checks for manually scheduling an asset and saving explicit defaults."""

import json
from pathlib import Path

import pytest
from jinja2 import Environment, StrictUndefined


@pytest.fixture(scope="module", autouse=True)
def setup_ui_test_data():
    """The modal's browser checks do not need the UI database fixtures."""


def modal_setup():
    """Exercise the same modal markup and module that the asset page loads."""
    template = (
        Path(__file__).resolve().parents[2] / "templates/assets/run_schedule.html"
    )
    markup = (
        Environment(autoescape=True, undefined=StrictUndefined)
        .from_string(template.read_text())
        .render(asset={"id": 3}, url_for=lambda *args, **kwargs: "/assets/3/context")
    )
    return f"""
        import {{ initializeRunSchedule }} from "/js/run-schedule.js";
        document.body.insertAdjacentHTML("beforeend", {json.dumps(markup)});
        const root = document.getElementById("runScheduleModal");
        const field = role => root.querySelector(`[data-role="${{role}}"]`);
        const requests = [];
        const pending = [];
        window.fetch = (url, options = {{}}) => {{
            requests.push({{url: String(url), options}});
            return new Promise((resolve, reject) => pending.push({{resolve, reject}}));
        }};
        const tick = () => new Promise(resolve => setTimeout(resolve, 0));
        const answer = async (data, status = 200) => {{
            check("there is a request awaiting its response", pending.length > 0);
            pending.shift().resolve({{ok: status < 400, status, json: async () => data}});
            await tick();
        }};
        const notices = [];
        window.showToast = (...args) => notices.push(args);
        initializeRunSchedule(root, {{
            optionsUrl: "/assets/3/scheduling-options",
            defaultsUrl: "/assets/3/scheduling-defaults",
            triggerUrl: "/api/v3_0/assets/3/schedules/trigger",
            jobsUrl: "/api/v3_0/jobs",
            configUrl: "/assets/3/context",
        }});
    """


OPTIONS = """
    const available = {
        power_sensors: [{id: 7, name: "Battery power", unit: "kW", url: "/sensors/7"}],
        consumption_price: null, power_capacity: null,
        price_sensors: [{id: 12, name: "Day-ahead", unit: "EUR/MWh"}],
        soc_sensors: [{id: 13, name: "Battery charge", value: 4.5, unit: "kWh",
                       event_start: "2026-10-14T09:00:00Z"}],
        warnings: [], can_save: true,
    };
    const open = () => root.dispatchEvent(new Event("show.bs.modal"));
    const change = role => field(role).dispatchEvent(new Event("change"));
    const submit = () => field("form").dispatchEvent(new Event("submit", {cancelable: true}));
    const chooseDefaults = () => {
        field("price").value = "12";
        field("capacity").value = "10";
        change("capacity");
    };
"""


def test_lookup_is_lazy_and_disables_dependent_controls(assert_js):
    assert_js(modal_setup() + OPTIONS + """
        eq("asset page initialization performs no lookup", requests.length, 0);
        open();
        eq("opening starts one lookup", requests.length, 1);
        check("price selection waits for lookup", field("price").disabled);
        check("SoC selection waits for lookup", field("soc-source").disabled);
        check("run waits for lookup", field("run").disabled);
        check("loading is announced", notices.some(item => item[0].includes("Checking prerequisites")));
        await answer(available);
        check("price field is ready", !field("price").disabled);
        check("missing defaults still prevent running", field("run").disabled);
        chooseDefaults();
        check("explicit defaults allow running", !field("run").disabled);
        eq("nothing is saved just by choosing", requests.length, 1);
    """)


def test_period_lookup_ignores_stale_responses_and_can_retry_failure(assert_js):
    assert_js(modal_setup() + OPTIONS + """
        open();
        field("duration").value = "12";
        change("duration");
        check("old lookup is aborted", requests[0].options.signal.aborted);
        const latest = pending.pop();
        latest.resolve({ok: true, status: 200, json: async () => ({...available, price_sensors: [
            {id: 15, name: "Current prices", unit: "EUR/MWh"}
        ]})});
        await tick();
        await answer(available);
        eq("late old result cannot replace latest choices", field("price").options[1].value, "15");
        change("duration");
        await answer({message: "Price lookup unavailable"}, 503);
        check("failed lookup prevents running", field("run").disabled);
        check("failure is explained", field("status").textContent.includes("Price lookup unavailable"));
        check("retry is offered", !field("retry").classList.contains("d-none"));
        field("retry").click();
        await answer(available);
        chooseDefaults();
        check("retry restores a usable form", !field("run").disabled);
    """)


def test_run_payload_completion_and_explicit_persistence(assert_js):
    assert_js(
        modal_setup() + OPTIONS + """
        // Poll immediately while preserving asynchronous task ordering.
        const realTimeout = window.setTimeout;
        window.setTimeout = (callback, delay) => realTimeout(callback, delay === 3000 ? 0 : delay);
        field("start").value = "2026-10-14T10:00";
        field("duration").value = "2";
        open();
        await answer(available);
        chooseDefaults();
        field("soc-source").value = "13";
        change("soc-source");
        check("a selected reading disables manual SoC", field("soc").disabled);
        field("force").checked = true;
        submit();
        check("inputs lock during execution", field("inputs").disabled);
        const payload = JSON.parse(requests[1].options.body);
        eq("duration is elapsed time", payload.duration, "PT7200S");
        eq("browser-local time becomes UTC", payload.start, "2026-10-14T08:00:00.000Z");
        eq("explicit force flag is sent", payload["force-new-job-creation"], true);
        eq("price belongs to flex-context", payload["flex-context"], {"consumption-price": {sensor: 12}});
        eq("device overrides carry units", payload["flex-model"], [
            {sensor: 7, "power-capacity": "10 kW", "soc-at-start": "4.5 kWh"}
        ]);
        await answer({job: "job-42"});
        await tick();
        eq("poll uses returned job id", requests[2].url, "/api/v3_0/jobs/job-42");
        await answer({status: "STARTED", message: "Schedule is running"}, 202);
        await tick();
        check("execution progress is announced", notices.some(item => item[0].includes("Schedule is running")));
        await answer({status: "FINISHED"});
        const link = field("results").querySelector("a");
        eq("completed result links to the power sensor", new URL(link.href).pathname, "/sensors/7");
        eq("result carries chosen period", new URL(link.href).searchParams.get("end_time"), "2026-10-14T10:00:00.000Z");
        check("save is offered after success", !field("save-group").classList.contains("d-none"));
        eq("success does not save automatically", requests.length, 4);
        field("save").click();
        eq("save uses a separate endpoint", requests[4].url, "/assets/3/scheduling-defaults");
        eq("only reusable defaults are saved", JSON.parse(requests[4].options.body),
            {consumption_price_sensor: 12, power_capacity: "10 kW"});
        await answer({message: "Saved"});
        await answer({...available, consumption_price: {sensor: 12}, power_capacity: "10 kW"});
        check("saved defaults are acknowledged", notices.some(item => item[0].includes("Defaults saved")));
        check("save prompt is dismissed", field("save-group").classList.contains("d-none"));
    """,
        timezone="Europe/Amsterdam",
    )


def test_failed_job_does_not_offer_success_or_save(assert_js):
    assert_js(modal_setup() + OPTIONS + """
        open();
        await answer(available);
        chooseDefaults();
        field("soc").value = "30";
        field("soc-unit").value = "MWh";
        submit();
        eq("manual SoC preserves selected unit", JSON.parse(requests[1].options.body)["flex-model"][0]["soc-at-start"], "30 MWh");
        await answer({message: "Scheduling configuration is incomplete"}, 422);
        check("failure is visible", field("status").textContent.includes("configuration is incomplete"));
        check("failure restores inputs", !field("inputs").disabled);
        check("no success result is shown", field("results").classList.contains("d-none"));
        check("no defaults are offered for saving", field("save-group").classList.contains("d-none"));
    """)


def test_missing_power_sensor_blocks_schedule_and_escapes_warnings(assert_js):
    assert_js(modal_setup() + OPTIONS + """
        open();
        await answer({...available, power_sensors: [], warnings: ["<img src=x onerror=alert(1)>"]});
        chooseDefaults();
        check("missing power sensor blocks run", field("run").disabled);
        check("prerequisite is explained", field("warnings").textContent.includes("No power sensor exists"));
        check("server-provided notes are text", field("warnings").querySelector("img") === null);
        submit();
        eq("no job is submitted", requests.length, 1);
    """)


def test_existing_defaults_are_preserved_and_period_edits_require_lookup(assert_js):
    assert_js(modal_setup() + OPTIONS + """
        open();
        const configured = {...available, consumption_price: 0, power_capacity: "20 kW"};
        await answer(configured);
        check("configured zero price is valid", !field("run").disabled);
        check("price override is hidden", field("price-group").classList.contains("d-none"));
        check("capacity override is hidden", field("capacity-group").classList.contains("d-none"));
        field("duration").value = "48";
        field("duration").dispatchEvent(new Event("input"));
        check("editing the period invalidates previous lookup", field("run").disabled);
        change("duration");
        await answer(configured);
        submit();
        const payload = JSON.parse(requests[2].options.body);
        eq("configured price is inherited", payload["flex-context"], undefined);
        eq("configured device defaults are inherited", payload["flex-model"], [{sensor: 7}]);
        eq("repeat job is opt-in", payload["force-new-job-creation"], false);
        await answer({message: "Validation failed"}, 422);
    """)
