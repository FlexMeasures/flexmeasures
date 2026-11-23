"""Tests for the sensor status page's row function in sensors/status.html.

The endpoint returns kebab-case field names alongside the deprecated snake_case
ones, and the page reads the kebab-case fields. These tests feed the row function
statuses that carry ONLY the kebab-case fields, so a missed migration would
render empty cells instead of values.
"""

import re

import pytest


@pytest.fixture(scope="module")
def status_row_js():
    """Extract the row function and its escapeHtml helper from the page.

    The row function also calls getTimeAgo and
    getHumanFriendlyDeltaOrTimeStr from flexmeasures.js; minimal stand-ins keep
    this test about field names.
    """
    template = open("flexmeasures/ui/templates/sensors/status.html").read()
    match = re.search(
        r"function escapeHtml\(value\) \{.*?\n  \}\n\n  function SensorStatusRow\(sensor\) \{.*?\n  \}\n",
        template,
        re.S,
    )
    assert match, "the status page carries the row function"
    return """
        const getTimeAgo = () => "just now";
        const getHumanFriendlyDeltaOrTimeStr = (iso) => iso;
        """ + match.group(0)


def test_row_reads_kebab_case_fields(assert_js, status_row_js):
    assert_js(status_row_js + """
        const row = SensorStatusRow({
          id: 5,
          name: "power",
          resolution: "PT15M",
          stale: false,
          "staleness-since": "2026-10-29T08:00:00+00:00",
          "source-type": "reporter",
          "asset-id": 12,
          "asset-name": "Heat & Pump",
          relation: "sensor belongs to this asset",
        });
        eq("asset cell names the asset", row.asset.includes("Heat &amp; Pump"), true);
        eq("asset cell links by id", row.asset.includes("/assets/12"), true);
        eq("source type read from kebab field", row["source-type"], "reporter");
        eq("timestamp kept as title", row["staleness-since"].includes("2026-10-29T08:00:00+00:00"), true);
        """)


def test_row_keeps_the_never_fallback(assert_js, status_row_js):
    assert_js(status_row_js + """
        const row = SensorStatusRow({
          id: 5,
          name: "power",
          resolution: "PT0S",
          stale: true,
          "staleness-since": null,
          "source-type": null,
          "asset-id": 12,
          "asset-name": "Street",
          relation: "sensor belongs to this asset",
        });
        eq("null timestamp shows Never", row["staleness-since"].includes("Never"), true);
        eq("null source type shows None", row["source-type"], "None");
        """)
