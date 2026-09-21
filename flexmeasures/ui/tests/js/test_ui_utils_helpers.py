"""Tests for the helpers in flexmeasures/ui/static/js/ui-utils.js that need no page around them."""

CAPTURE_TOASTS = """
const toasts = [];
window.showToast = (message, type) => toasts.push({message, type});
"""


def test_move_array_item(assert_js):
    assert_js("""
        import { moveArrayItem } from "/js/ui-utils.js";
        const items = ["a", "b", "c"];
        eq("moving up swaps with the item before", moveArrayItem(items, 1, "up"), ["b", "a", "c"]);
        eq("moving down swaps with the item after", moveArrayItem(items, 1, "down"), ["a", "c", "b"]);
        eq("the first item cannot move up", moveArrayItem(items, 0, "up"), items);
        eq("the last item cannot move down", moveArrayItem(items, 2, "down"), items);
        eq("the original is untouched", items, ["a", "b", "c"]);
        check("a new array is returned", moveArrayItem(items, 0, "up") !== items);
        """)


def test_flatten_error_payload(assert_js):
    assert_js("""
        import { flattenErrorPayload } from "/js/ui-utils.js";
        eq("a plain message stays as it is", flattenErrorPayload("Not found"), ["Not found"]);
        eq("nothing gives nothing", flattenErrorPayload(null), []);
        eq("nested fields are named by their path",
           flattenErrorPayload({flex_context: {"site-power-capacity": ["Not a valid quantity."]}}),
           ["\\n <b>flex_context.site-power-capacity</b>: Not a valid quantity."]);
        eq("each message in a list is kept",
           flattenErrorPayload({name: ["Too short.", "Not unique."]}).length, 2);
        """)


def test_extract_api_error_message(assert_js):
    """Marshmallow errors arrive under message.json, other errors under message or error."""
    assert_js("""
        import { extractApiErrorMessage } from "/js/ui-utils.js";
        eq("validation errors are preferred",
           extractApiErrorMessage({message: {json: {name: ["Missing data for required field."]}}, status: 422}),
           "<b>name</b>: Missing data for required field.");
        eq("then a message", extractApiErrorMessage({message: "Asset not found", status: 404}), "Asset not found");
        eq("then an error", extractApiErrorMessage({error: "Forbidden"}), "Forbidden");
        eq("several messages are joined",
           extractApiErrorMessage({message: {json: {a: ["x"], b: ["y"]}}}), "<b>a</b>: x; <b>b</b>: y");
        eq("without a body, the fallback is used", extractApiErrorMessage(null, "Bad Gateway"), "Bad Gateway");
        eq("without either, something is still said", extractApiErrorMessage(undefined), "Unknown error");
        eq("an empty body falls back too", extractApiErrorMessage({}, "Bad Request"), "Bad Request");
        """)


def test_reactive_state(assert_js):
    assert_js("""
        import { createReactiveState } from "/js/ui-utils.js";
        const rendered = [];
        const [get, set] = createReactiveState(1, (value) => rendered.push(value));
        eq("the initial value is rendered right away", rendered, [1]);
        set(2);
        eq("setting a value renders it", [get(), rendered], [2, [1, 2]]);
        set((previous) => previous * 10);
        eq("a function is applied to the current value", get(), 20);
        const [getQuiet, setQuiet] = createReactiveState("a");
        setQuiet("b");
        eq("a render function is optional", getQuiet(), "b");
        """)


def test_convert_html_to_element(assert_js):
    assert_js("""
        import { convertHtmlToElement } from "/js/ui-utils.js";
        const element = convertHtmlToElement("  <div class='card'><b>hi</b></div>  ");
        eq("surrounding whitespace does not become the element", element.tagName, "DIV");
        eq("the markup is kept", element.querySelector("b").textContent, "hi");
        """)


def test_python_repr_to_json(assert_js):
    """Jinja renders a dict as its Python representation, which the page has to read back."""
    assert_js("""
        import { pythonReprToJSON } from "/js/ui-utils.js";
        const read = (repr) => JSON.parse(pythonReprToJSON(repr));
        eq("the constants are translated",
           read("{'a': None, 'b': True, 'c': False, 'd': 1.5}"), {a: null, b: true, c: false, d: 1.5});
        eq("constants inside strings are left alone",
           read("{'note': 'None of this is True'}"), {note: "None of this is True"});
        eq("an apostrophe survives, as Python writes it", read(`{'name': "Bob's contract"}`), {name: "Bob's contract"});
        eq("both kinds of quote survive", read(`{'name': 'Bob\\\\'s "big" contract'}`), {name: `Bob's "big" contract`});
        eq("escapes are read", read("{'a': 'line\\\\nbreak', 'b': '\\\\\\\\', 'c': 'caf\\\\xe9'}"), {a: "line\\nbreak", b: "\\\\", c: "café"});
        eq("nesting is kept", read("{'commitments': [{'name': 'x', 'baseline': {'sensor': 3}}]}"),
           {commitments: [{name: "x", baseline: {sensor: 3}}]});
        """)


def test_process_resource_raw_json(assert_js):
    assert_js("""
        import { processResourceRawJSON } from "/js/ui-utils.js";
        const schema = {"soc-min": null, "soc-max": null};
        const [values, extra] = processResourceRawJSON(schema, "{'soc-min': '10 kWh', 'foo': 'bar'}", true);
        eq("the stored values are returned", values, {"soc-min": "10 kWh", foo: "bar"});
        eq("fields the schema does not know are reported", extra, {foo: "bar"});
        eq("the schema takes the stored values", schema, {"soc-min": "10 kWh", "soc-max": null, foo: "bar"});

        const [fromObject] = processResourceRawJSON({}, {"site-power-capacity": "1 MW"}, true);
        eq("stored values may also be passed as an object", fromObject, {"site-power-capacity": "1 MW"});

        const [quoted] = processResourceRawJSON({}, `{'commitments': [{'name': "Bob's"}], 'note': 'Nonetheless'}`, true);
        eq("values are not mangled", quoted, {commitments: [{name: "Bob's"}], note: "Nonetheless"});
        """)


def test_resources_are_fetched_once_and_then_cached(assert_js):
    assert_js("""
        import { getAsset, getSensor, getAccount } from "/js/ui-utils.js";
        localStorage.clear();
        const requests = [];
        window.fetch = async (url) => { requests.push(url); return {json: async () => ({id: requests.length, url})}; };

        const first = await getSensor(5);
        const again = await getSensor(5);
        eq("a sensor is fetched from the API", requests.length, 1);
        check("at its endpoint", requests[0].endsWith("/api/v3_0/sensors/5"), requests[0]);
        eq("and then answered from the cache", again, first);

        await getAccount(2);
        await getAccount(2);
        eq("so is an account", requests.length, 2);

        await getAsset(3);
        await getAsset(3);
        eq("and an asset", requests.length, 3);
        await getAsset(3, false);
        eq("unless the cache is explicitly bypassed", requests.length, 4);
        localStorage.clear();
        """)


def test_poll_job_status_until_finished(assert_js):
    assert_js(CAPTURE_TOASTS + """
        import { pollJobStatus } from "/js/ui-utils.js";
        const answers = [{status: "queued"}, {status: "STARTED", message: "Ingesting"}, {status: "finished"}];
        const requests = [];
        window.fetch = async (url) => {
            requests.push(url);
            return {ok: true, json: async () => answers[Math.min(requests.length - 1, answers.length - 1)]};
        };
        const done = new Promise((resolve) => pollJobStatus("a b", {intervalMs: 5, onFinished: resolve}));
        const finished = await done;
        eq("the job's own endpoint is polled, with its id encoded",
           requests[0].endsWith("/api/v3_0/jobs/a%20b"), true);
        eq("polling stops when the job is done", finished.status, "finished");
        eq("the viewer is kept informed", toasts.map((t) => t.message), ["Processing…", "Ingesting", "Job completed successfully."]);
        const polled = requests.length;
        await new Promise((resolve) => setTimeout(resolve, 30));
        eq("and nothing is polled afterwards", requests.length, polled);
        """)


def test_poll_job_status_reports_failure(assert_js):
    assert_js(CAPTURE_TOASTS + """
        import { pollJobStatus } from "/js/ui-utils.js";
        window.fetch = async () => ({ok: true, json: async () => ({status: "FAILED", message: "Bad data in row 3"})});
        const failed = await new Promise((resolve) => pollJobStatus("x", {intervalMs: 5, onFailed: resolve}));
        eq("the failure is passed on", failed.message, "Bad data in row 3");
        eq("and shown", toasts.at(-1), {message: "Bad data in row 3", type: "error"});

        window.fetch = async () => ({ok: false, status: 502, statusText: "Bad Gateway"});
        const unreachable = await new Promise((resolve) => pollJobStatus("x", {intervalMs: 5, onFailed: resolve}));
        eq("an unreachable endpoint counts as a failure without a job", unreachable, null);
        check("and says so", toasts.at(-1).message.includes("HTTP 502"), toasts.at(-1).message);
        """)


def test_poll_job_status_can_be_stopped(assert_js):
    assert_js(CAPTURE_TOASTS + """
        import { pollJobStatus } from "/js/ui-utils.js";
        let polls = 0;
        window.fetch = async () => { polls++; return {ok: true, json: async () => ({status: "QUEUED"})}; };
        const controller = new AbortController();
        const stop = pollJobStatus("x", {intervalMs: 5, signal: controller.signal});
        await new Promise((resolve) => setTimeout(resolve, 30));
        controller.abort();
        const atAbort = polls;
        await new Promise((resolve) => setTimeout(resolve, 30));
        eq("aborting the signal stops polling", polls, atAbort);
        check("after having polled more than once", atAbort > 1, String(atAbort));
        eq("a stop function is returned too", typeof stop, "function");
        """)


def test_escape_html(assert_js):
    assert_js("""
        import { escapeHtml, unitHtml } from "/js/ui-utils.js";
        eq("markup becomes text", escapeHtml(`<img src=x onerror="alert('hi')"> & more`),
           "&lt;img src=x onerror=&quot;alert(&#39;hi&#39;)&quot;&gt; &amp; more");
        eq("nothing becomes the empty string", [escapeHtml(null), escapeHtml(undefined)], ["", ""]);
        eq("numbers are written as they are", escapeHtml(4.5), "4.5");

        const holder = document.createElement("div");
        holder.innerHTML = `<b title="${escapeHtml('" onmouseover="x')}">${escapeHtml("<i>name</i>")}</b>`;
        eq("an escaped value stays inside its attribute", holder.firstChild.getAttributeNames(), ["title"]);
        eq("and inside its element", holder.firstChild.children.length, 0);

        eq("a unit is escaped", unitHtml("<b>kW</b>"), "&lt;b&gt;kW&lt;/b&gt;");
        check("an empty unit is explained", unitHtml("").includes(">dimensionless</span>"), unitHtml(""));
        """)


def test_process_resource_raw_json_reads_json_too(assert_js):
    """The API sends a flex-context or flex-model as a JSON string, which the asset graph page passes on."""
    assert_js("""
        import { processResourceRawJSON } from "/js/ui-utils.js";
        const [values] = processResourceRawJSON({}, JSON.stringify({"prefer-charging-sooner": true, "soc-min": null, name: "Bob's"}), true);
        eq("JSON is read as it is", values, {"prefer-charging-sooner": true, "soc-min": null, name: "Bob's"});
        """)


def test_rendered_sensors_show_names_as_text(assert_js):
    assert_js("""
        import { renderSensor } from "/js/ui-utils.js";
        localStorage.clear();
        const hostile = "<img src=x onerror=window.__ran=1>";
        window.fetch = async (url) => ({json: async () =>
            url.includes("/sensors/") ? {id: 1, name: hostile, unit: "", generic_asset_id: 2}
            : url.includes("/assets/") ? {id: 2, name: hostile, account_id: 3}
            : {id: 3, name: hostile}});
        const holder = document.createElement("div");
        holder.innerHTML = await renderSensor(1);
        eq("no element is made from a name", holder.querySelectorAll("img").length, 0);
        check("the names are shown as they were typed", holder.textContent.includes(hostile), holder.textContent);
        check("a dimensionless sensor says so", holder.textContent.includes("dimensionless"), holder.textContent);
        localStorage.clear();
        """)
