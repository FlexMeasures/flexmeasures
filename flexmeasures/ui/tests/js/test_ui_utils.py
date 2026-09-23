"""Browser checks for the small preference helpers in `ui-utils.js`."""

import pytest


@pytest.fixture(scope="module", autouse=True)
def setup_ui_test_data():
    """These checks run the module on its own, so they need no database fixtures."""


PREAMBLE = """
import { setDefaultAssetView } from "/js/ui-utils.js";

const toasts = [];
window.showToast = (message, type) => toasts.push({message, type});

function stubFetch(response) {
    const calls = [];
    window.fetch = (url, options) => {
        calls.push({url, options});
        return Promise.resolve(response);
    };
    return calls;
}

const checkbox = document.createElement("input");
checkbox.type = "checkbox";
"""


def test_a_stored_default_view_leaves_the_checkbox_alone(assert_js):
    assert_js(PREAMBLE + """
        const calls = stubFetch(new Response("{}", {status: 200, headers: {"content-type": "application/json"}}));
        checkbox.checked = true;
        await setDefaultAssetView(checkbox, "Automations");

        eq("the view the user is on is what gets sent", JSON.parse(calls[0].options.body).default_asset_view, "Automations");
        check("the checkbox keeps the tick the click gave it", checkbox.checked === true);
        eq("nothing is reported to the user", toasts.length, 0);
        """)


def test_a_refused_default_view_is_reported_and_unticked(assert_js):
    assert_js(PREAMBLE + """
        // The shape webargs actually returns for a value the schema refuses.
        stubFetch(new Response(
            JSON.stringify({message: {json: {default_asset_view: ["Must be one of: Context, Graphs."]}}}),
            {status: 422, statusText: "UNPROCESSABLE ENTITY", headers: {"content-type": "application/json"}},
        ));
        checkbox.checked = true;
        await setDefaultAssetView(checkbox, "Nonsense");

        check("the checkbox goes back to what the server still has", checkbox.checked === false);
        eq("the refusal is reported once", toasts.length, 1);
        eq("the toast is an error", toasts[0].type, "error");
        check(
            "the server's own reason reaches the user",
            toasts[0].message.includes("Must be one of: Context, Graphs."),
            toasts[0].message,
        );
        """)


def test_a_network_failure_is_reported_too(assert_js):
    assert_js(PREAMBLE + """
        window.fetch = () => Promise.reject(new Error("Failed to fetch"));
        checkbox.checked = false;
        await setDefaultAssetView(checkbox, "Context");

        check("the checkbox goes back to ticked", checkbox.checked === true);
        eq("the failure is reported", toasts.length, 1);
        eq("the toast is an error", toasts[0].type, "error");
        """)
