"""The selected graph window follows users between sensor and asset pages."""

import json
import re
from pathlib import Path

from jinja2 import Environment


def test_selected_window_survives_navigation_without_fetching_chart_specs(assert_js):
    assert_js("""
        import { restoreChartDateRange, rememberChartDateRange } from "/js/chart-date-range.js";
        localStorage.clear();
        const start = new Date("2024-03-30T00:00:00+01:00");
        const end = new Date("2024-04-02T00:00:00+02:00");
        rememberChartDateRange(start, end);
        for (const page of ["sensor B", "asset", "sensor A"]) {
            const restored = restoreChartDateRange("", "2020-01-01", "2020-01-02");
            eq(`${page} keeps the selected start`, restored.start.getTime(), start.getTime());
            eq(`${page} keeps the exclusive end across DST`, restored.end.getTime(), end.getTime());
        }
        // A narrower selection can be entirely cached: persistence must need no data request.
        const narrowerEnd = new Date("2024-04-01T00:00:00+02:00");
        rememberChartDateRange(start, narrowerEnd);
        eq("a cached selection is remembered", restoreChartDateRange("").end.getTime(), narrowerEnd.getTime());
        localStorage.clear();
    """)


def test_explicit_link_wins_and_legacy_session_is_a_fallback(assert_js):
    assert_js("""
        import { restoreChartDateRange, rememberChartDateRange } from "/js/chart-date-range.js";
        localStorage.clear();
        eq("a fresh browser has no remembered range", restoreChartDateRange(""), null);
        const fallback = restoreChartDateRange("", "2023-02-01", "2023-02-03");
        eq("legacy sessions still work", fallback.start.toISOString(), "2023-02-01T00:00:00.000Z");
        rememberChartDateRange("2024-01-01", "2024-01-04");
        for (const plus of ["+", "%2B"]) {
            const range = restoreChartDateRange(
                `?start_time=2025-03-01T00:00:00${plus}01:00&end_time=2025-03-03T00:00:00${plus}01:00`,
                "2023-02-01", "2023-02-03"
            );
            eq("shared links override stored dates, including positive offsets", range.start.toISOString(), "2025-02-28T23:00:00.000Z");
            eq("linked end stays exclusive", range.end.toISOString(), "2025-03-02T23:00:00.000Z");
        }
        eq("an incomplete link does not mix date sources", restoreChartDateRange("?start_time=2025-01-01").start.getUTCFullYear(), 2024);
        localStorage.clear();
    """)


def test_clearing_the_session_forgets_the_selected_window(assert_js):
    assert_js("""
        import { restoreChartDateRange, rememberChartDateRange, forgetChartDateRange } from "/js/chart-date-range.js";
        localStorage.clear();
        rememberChartDateRange("2024-01-01", "2024-01-04");
        forgetChartDateRange();
        eq("a forgotten range is not restored", restoreChartDateRange(""), null);
        eq("the session range applies again", restoreChartDateRange("", "2023-02-01", "2023-02-03").start.toISOString(), "2023-02-01T00:00:00.000Z");
        const descriptor = Object.getOwnPropertyDescriptor(window, "localStorage");
        Object.defineProperty(window, "localStorage", { configurable: true, get() { throw new Error("Storage blocked"); } });
        try {
            forgetChartDateRange();
            eq("blocked storage does not break forgetting", true, true);
        } finally {
            Object.defineProperty(window, "localStorage", descriptor);
            localStorage.clear();
        }
    """)


def test_invalid_or_unavailable_storage_does_not_break_graphs(assert_js):
    assert_js("""
        import { restoreChartDateRange, rememberChartDateRange } from "/js/chart-date-range.js";
        localStorage.clear();
        for (const saved of ["broken", "null", '{}', '{"start":"bad","end":"2024-01-03"}', '{"start":"2024-01-03","end":"2024-01-01"}']) {
            localStorage.setItem("fm-chart-date-range", saved);
            eq("invalid saved data falls back to session", restoreChartDateRange("", "2023-01-01", "2023-01-02").start.getUTCFullYear(), 2023);
        }
        rememberChartDateRange("2024-01-01", "2024-01-03");
        rememberChartDateRange("bad", "2024-01-04");
        eq("invalid selections do not replace the remembered range", restoreChartDateRange("").end.getUTCDate(), 3);
        const descriptor = Object.getOwnPropertyDescriptor(window, "localStorage");
        Object.defineProperty(window, "localStorage", { configurable: true, get() { throw new Error("Storage blocked"); } });
        try {
            rememberChartDateRange("2024-01-01", "2024-01-03");
            eq("blocked storage falls back safely", restoreChartDateRange("", "2023-01-01", "2023-01-02").start.getUTCFullYear(), 2023);
        } finally {
            Object.defineProperty(window, "localStorage", descriptor);
            localStorage.clear();
        }
    """)


def test_graph_template_remembers_picker_selection_across_pages(assert_js):
    """Execute the template's picker and initialization wiring, without rendering charts.

    Chart requests are intentionally outside this test: saving a cached selection
    must work before any chart response can update a server session.
    """
    template_path = (
        Path(__file__).resolve().parents[2] / "templates/includes/graphs.html"
    )
    source = template_path.read_text()
    initialization = re.search(
        r"    (?:const initialRange|{% if event_starts_after and event_ends_before %})"
        r".*?(?=    {% if active_page == \"sensors\" and sensor.event_resolution)",
        source,
        re.DOTALL,
    ).group()
    # Keep the real selected handler through its state changes and notification,
    # stopping before chart loading/replay. Nothing below that boundary saves dates.
    selection = source.split("picker.on('selected', (startDate, endDate) => {", 1)[1]
    selection = selection.split("    stopReplay()", 1)[0]
    env = Environment()
    snippets = []
    for active_page in ("sensors", "assets"):
        context = dict(
            active_page=active_page,
            sensor={"id": 1},
            FLEXMEASURES_MODE="normal",
            event_starts_after="2020-01-01T00:00:00Z",
            event_ends_before="2020-01-03T00:00:00Z",
        )
        snippets.append(
            {
                "page": active_page,
                "initialization": env.from_string(initialization).render(**context),
                "selection": env.from_string(selection).render(**context),
            }
        )
    assert_js(
        """
        import { restoreChartDateRange, rememberChartDateRange } from "/js/chart-date-range.js";
        const snippets = """
        + json.dumps(snippets)
        + """;
        localStorage.clear();
        const checkbox = document.createElement("input");
        checkbox.id = "toggleStatsCheckbox";
        document.body.append(checkbox);
        const toIsoString = date => date.toISOString();
        const loadSensorStats = () => {};
        let storeStartDate, storeEndDate, fastChartWindow;
        const start = new Date("2024-05-06T00:00:00Z");
        const inclusiveEnd = new Date("2024-05-08T00:00:00Z");
        const wrap = date => ({toJSDate: () => new Date(date)});
        for (const origin of snippets) {
            window.history.replaceState({}, "", window.location.pathname);
            // The selected handler is the actual rendered code used by each page.
            const select = (startDate, endDate) => eval(origin.selection);
            select(wrap(start), wrap(inclusiveEnd));
            eq(`${origin.page} uses an exclusive data window`, storeEndDate.toISOString(), "2024-05-09T00:00:00.000Z");
            // Navigating to another graph loses the source page's query parameters.
            window.history.replaceState({}, "", window.location.pathname);
            for (const destination of snippets) {
                let sessionStart = null, sessionEnd = null;
                eval(destination.initialization);
                eq(`${origin.page} to ${destination.page} restores the picker start`, sessionStart.toISOString(), start.toISOString());
                eq(`${origin.page} to ${destination.page} restores the inclusive picker end`, sessionEnd.toISOString(), inclusiveEnd.toISOString());
            }
        }
        localStorage.clear();
        """,
        timezone="UTC",
    )
