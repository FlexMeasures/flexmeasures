"""Tests for flexmeasures/ui/static/js/audit-log.js, with the real jQuery and DataTables.

Event texts hold asset, user and account names, and whatever plugins write,
so the audit-log tables must show them as text rather than insert them as HTML.
"""

import json

MALICIOUS_EVENT = (
    'Updated asset \'<img src="x" onerror="window.__ran = (window.__ran || 0) + 1">\''
)
MALICIOUS_USER = '<img src="x" onerror="window.__ran = (window.__ran || 0) + 1">'


def load_scripts(paths: list[str]) -> str:
    """JavaScript that loads classic scripts one after another, as base.html does."""
    return f"""
for (const src of {json.dumps(paths)}) {{
    await new Promise((resolve, reject) => {{
        const script = document.createElement("script");
        script.src = src;
        script.onload = resolve;
        script.onerror = () => reject(new Error(`could not load ${{src}}`));
        document.head.append(script);
    }});
}}
"""


def test_audit_log_shows_events_and_users_as_text(assert_js, datatables_paths):
    assert_js(load_scripts(datatables_paths) + f"""
        const event = {json.dumps(MALICIOUS_EVENT)};
        const userName = {json.dumps(MALICIOUS_USER)};
        $.ajax = (options) => options.success({{
            data: [{{
                event_datetime: "2026-11-17T10:00:00+00:00",
                event: event,
                active_user_name: userName,
                active_user_id: 7,
            }}],
            "num-records": 1,
            "filtered-records": 1,
        }});
        const table = document.createElement("table");
        table.id = "auditLog";
        document.body.append(table);

        const {{ initAuditLogTable }} = await import("/js/audit-log.js");
        initAuditLogTable("#auditLog", "/api/v3_0/assets/1/auditlog");
        await new Promise((resolve) => setTimeout(resolve, 200));

        const cells = [...table.querySelectorAll("tbody td")].map((td) => td.textContent);
        eq("the row shows the event text as given", cells[1], event);
        eq("the row shows the acting user as given", cells[2], `${{userName}} (Id: 7)`);
        eq("no element is created from the event or user name", table.querySelectorAll("tbody img").length, 0);
        eq("no event handler from the data ran", window.__ran, undefined);
        check("the event time is still shown as a date", table.querySelector("tbody td span[title]") !== null);
        """)
