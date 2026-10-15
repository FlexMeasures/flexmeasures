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
        consumption_price: null, power_capacity: null, requires_soc: true,
        price_sensors: [{id: 12, name: "Day-ahead", unit: "EUR/MWh", url: "/sensors/12"}],
        soc_sensors: [{id: 13, name: "Battery charge", value: 4.5, unit: "kWh",
                       event_start: "2026-10-14T09:00:00Z"}],
        warnings: [], can_save: true,
    };
    const open = () => root.dispatchEvent(new Event("show.bs.modal"));
    const change = role => field(role).dispatchEvent(new Event("change"));
    const submit = () => field("form").dispatchEvent(new Event("submit", {cancelable: true}));
    const chooseDefaults = () => {
        field("price").value = "12";
        change("price");
        field("capacity").value = "10";
        change("capacity");
        field("soc").value = "0";
        field("soc").dispatchEvent(new Event("input"));
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
        eq("disabled button wrapper has a hoverable explanation", field("run-tooltip").title, "Disable, check prerequisites warnings.");
        check("disabled button wrapper can receive focus", field("run-tooltip").tabIndex === 0);
        check("loading is announced", notices.some(item => item[0].includes("Checking prerequisites")));
        await answer(available);
        eq("power sensor name links to its page", field("power").querySelector("a").getAttribute("href"), "/sensors/7");
        check("power sensor ID is visible", field("power").textContent.includes("ID: 7"));
        check("power sensor value has a label", root.querySelector('label[for="schedulePower"]').textContent.includes("Power sensor"));
        check("timing help spans both inputs", field("timezone").parentElement.classList.contains("col-12"));
        check("checked message is in an info box", field("status").classList.contains("alert-info") && !field("status").classList.contains("d-none"));
        check("price field is ready", !field("price").disabled);
        check("price choices include sensor IDs", field("price").options[1].textContent.includes("ID: 12"));
        check("missing defaults still prevent running", field("run").disabled);
        chooseDefaults();
        check("explicit defaults allow running", !field("run").disabled);
        eq("ready button has no disabled explanation", field("run-tooltip").title, "");
        eq("selected price sensor links to its page", field("selected-price").querySelector("a").getAttribute("href"), "/sensors/12");
        check("selected price sensor ID is visible", field("selected-price").textContent.includes("ID: 12"));
        check("SoC option describes an existing reading", field("soc-source").options[0].textContent.includes("existing SoC reading"));
        eq("manual SoC field prompts for a value", field("soc").placeholder, "Enter value");
        check("force checkbox keeps an associated label", root.querySelector('label[for="scheduleForce"]').classList.contains("form-check-label"));
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
        check("retry is a link in the footer", field("retry").tagName === "A" && field("retry").parentElement.classList.contains("modal-footer"));
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
        eq("success link says See it here", link.textContent, "See it here");
        eq("result shows five hours before the schedule", new URL(link.href).searchParams.get("start_time"), "2026-10-14T03:00:00.000Z");
        eq("result shows five hours after the schedule", new URL(link.href).searchParams.get("end_time"), "2026-10-14T15:00:00.000Z");
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
        check("asset is explicitly unsupported", field("warnings").textContent.includes("This asset has no power sensor, so it is not supported"));
        check("warnings are beside the action buttons", field("warnings").parentElement.classList.contains("modal-footer"));
        check("server-provided notes are text", field("warnings").querySelector("img") === null);
        submit();
        eq("no job is submitted", requests.length, 1);
    """)


def test_multiple_power_sensors_and_uncovered_configured_price_block_run(assert_js):
    assert_js(modal_setup() + OPTIONS + """
        open();
        await answer({...available, power_sensors: [available.power_sensors[0],
            {id: 8, name: "Other power", unit: "kW", url: "/sensors/8"}]});
        chooseDefaults();
        check("multiple power sensors block the action", field("run").disabled);
        check("power field explains the multiplicity", field("power").textContent.includes("More than one") && field("power").textContent.includes("see info below"));
        eq("power field links each sensor ID", [...field("power").querySelectorAll("a")].map(link => link.textContent), ["7", "8"]);
        check("warning says the asset is unsupported", field("warnings").textContent.includes("This asset has multiple power sensors, so it is not supported"));
        check("warning mentions upcoming support", field("warnings").textContent.includes("coming soon"));
        change("duration");
        await answer({...available, consumption_price: {sensor: 12}, price_available: false});
        field("capacity").value = "10";
        change("capacity");
        check("missing configured price coverage blocks the action", field("run").disabled);
        check("price coverage is explained", field("warnings").textContent.includes("no data covering the full schedule"));
    """)


def test_existing_defaults_are_preserved_and_period_edits_require_lookup(assert_js):
    assert_js(modal_setup() + OPTIONS + """
        open();
        const configured = {...available, consumption_price: 0, power_capacity: "20 kW", requires_soc: false};
        await answer(configured);
        check("configured zero price is valid", !field("run").disabled);
        eq("fixed price is displayed", field("configured-price").textContent, "0");
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


def test_configured_price_sensor_is_linked(assert_js):
    assert_js(modal_setup() + OPTIONS + """
        open();
        await answer({...available, consumption_price: {sensor: 12},
            consumption_price_sensor: {id: 12, name: "Inherited day-ahead", unit: "EUR/MWh", url: "/sensors/12"},
            power_capacity: "20 kW"});
        check("configured price replaces the selector", field("price-group").classList.contains("d-none"));
        check("configured price is visible", !field("configured-price-group").classList.contains("d-none"));
        eq("configured price links to its sensor", field("configured-price").querySelector("a").getAttribute("href"), "/sensors/12");
        eq("configured sensor name is shown", field("configured-price").querySelector("a").textContent, "Inherited day-ahead");
        check("configured price sensor ID is visible", field("configured-price").textContent.includes("ID: 12"));
    """)


def test_soc_selector_is_hidden_without_existing_readings(assert_js):
    assert_js(modal_setup() + OPTIONS + """
        open();
        await answer({...available, soc_sensors: []});
        check("no empty SoC chooser is shown", field("soc-source").classList.contains("d-none"));
        eq("manual value is still offered", field("soc").placeholder, "Enter value");
    """)


def test_storage_requires_a_starting_soc_but_non_storage_does_not(assert_js):
    assert_js(modal_setup() + OPTIONS + """
        open();
        await answer({...available, consumption_price: 0, power_capacity: "10 kW"});
        check("storage without SoC cannot run", field("run").disabled);
        check("missing SoC is explained", field("warnings").textContent.includes("starting state of charge"));
        field("soc").value = "0";
        field("soc").dispatchEvent(new Event("input"));
        check("zero SoC is valid", !field("run").disabled);
        field("soc").value = "-1";
        field("soc").dispatchEvent(new Event("input"));
        check("negative SoC is invalid", field("run").disabled);
        field("soc").value = "";
        field("soc-source").value = "13";
        change("soc-source");
        check("choosing a reading provides SoC", !field("run").disabled);
        change("duration");
        await answer({...available, consumption_price: 0, power_capacity: "10 kW", requires_soc: false});
        check("non-storage asset can run without SoC", !field("run").disabled);
    """)
