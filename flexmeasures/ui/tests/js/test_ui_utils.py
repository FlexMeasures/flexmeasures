"""Tests for flexmeasures/ui/static/js/ui-utils.js."""


def test_report_skipped_automations_says_which_ones_and_why(assert_js):
    assert_js("""
        import { reportSkippedAutomations } from "/js/ui-utils.js";
        const toasts = [];
        window.showToast = (message, type) => toasts.push({message, type});
        const reported = reportSkippedAutomations({
            asset: 99,
            "skipped-automations": [
                {id: 7, name: "Day-ahead PV forecasts", asset: 10, reason: "It references sensor 42."},
            ],
        });
        check("the caller is told something was reported", reported === true, String(reported));
        check("exactly one toast is shown", toasts.length === 1, JSON.stringify(toasts));
        check("the toast counts the automations", toasts[0].message.includes("1 automation(s) could not be copied"), toasts[0].message);
        check("the toast names the automation", toasts[0].message.includes("Day-ahead PV forecasts"), toasts[0].message);
        check("the toast gives the reason", toasts[0].message.includes("It references sensor 42."), toasts[0].message);
        """)


def test_report_skipped_automations_escapes_the_automation_name(assert_js):
    """An automation name is whatever a user typed, and the toast renders its message as HTML."""
    assert_js("""
        import { reportSkippedAutomations } from "/js/ui-utils.js";
        const toasts = [];
        window.showToast = (message, type) => toasts.push({message, type});
        reportSkippedAutomations({
            asset: 99,
            "skipped-automations": [
                {id: 7, name: "<img src=x onerror=alert(1)>", asset: 10, reason: "<b>bold</b>"},
            ],
        });
        const message = toasts[0].message;
        check("no raw tag survives into the message", !message.includes("<img"), message);
        check("no raw markup survives from the reason either", !message.includes("<b>"), message);
        check("the name is still readable as text", message.includes("&lt;img src=x onerror=alert(1)&gt;"), message);
        const holder = document.createElement("div");
        holder.innerHTML = message;
        check("rendering the message creates no elements of its own", holder.querySelector("img, b") === null, holder.innerHTML);
        """)


def test_report_skipped_automations_stays_quiet_when_all_were_copied(assert_js):
    """A copy that left nothing out should not raise a warning of its own."""
    assert_js("""
        import { reportSkippedAutomations } from "/js/ui-utils.js";
        const toasts = [];
        window.showToast = (message, type) => toasts.push({message, type});
        check("an empty list reports nothing", reportSkippedAutomations({asset: 99, "skipped-automations": []}) === false);
        check("a response without the field reports nothing", reportSkippedAutomations({asset: 99}) === false);
        check("no response at all reports nothing", reportSkippedAutomations(undefined) === false);
        eq("no toast was shown", toasts, []);
        """)
