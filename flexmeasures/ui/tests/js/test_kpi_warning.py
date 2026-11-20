"""Tests for the missing KPI days warning."""


def test_missing_kpi_days_warning_is_shown_once_and_resets(assert_js):
    assert_js("""
        const toasts = [];
        window.showToast = (message, type) => toasts.push({message, type});
        import { checkMissingKpiDays } from "/js/chart-data-utils.js";

        checkMissingKpiDays(true);
        eq("one warning is shown", toasts.length, 1);
        eq(
            "the warning explains how KPIs are calculated",
            toasts[0].message,
            "Some selected days have no results. KPIs are calculated only from days where the project was run."
        );
        eq("the warning is informational", toasts[0].type, "info");

        checkMissingKpiDays(true);
        eq("the same warning is not repeated", toasts.length, 1);

        checkMissingKpiDays(false);
        checkMissingKpiDays(true);
        eq("a complete response resets the warning", toasts.length, 2);
        """)


def test_missing_kpi_days_warning_ignores_false_or_absent_flag(assert_js):
    assert_js("""
        const toasts = [];
        window.showToast = (message, type) => toasts.push({message, type});
        import { checkMissingKpiDays } from "/js/chart-data-utils.js";

        checkMissingKpiDays(false);
        checkMissingKpiDays(undefined);
        eq("complete and older responses show no warning", toasts.length, 0);
        """)
