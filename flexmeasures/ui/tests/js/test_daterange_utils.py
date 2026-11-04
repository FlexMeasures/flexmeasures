"""Tests for flexmeasures/ui/static/js/daterange-utils.js."""


def test_to_iso_string_with_offset_keeps_the_instant(assert_js):
    """Formatting a date with a local offset must not move it in time.

    The KPI window is sent to the API through this function,
    so an instant that shifts by the local offset asks for the wrong days.
    """
    assert_js("""
        import { toIsoStringWithOffset } from "/js/daterange-utils.js";
        for (const date of [new Date(2022, 9, 2), new Date(2022, 0, 15, 13, 45, 30), new Date(2022, 6, 1)]) {
            const formatted = toIsoStringWithOffset(date);
            eq(`${formatted} parses back to the same instant`,
               new Date(formatted).getTime(), date.getTime());
        }
        check("the string carries an offset rather than a Z",
              /[+-]\\d{2}:\\d{2}$/.test(toIsoStringWithOffset(new Date(2022, 9, 2))),
              toIsoStringWithOffset(new Date(2022, 9, 2)));
        eq("the local clock time is written, not the UTC one",
           toIsoStringWithOffset(new Date(2022, 9, 2)).slice(0, 19), "2022-10-02T00:00:00");
        """)


def test_subtract_counts_whole_days(assert_js):
    assert_js("""
        import { subtract } from "/js/daterange-utils.js";
        const from = new Date(2022, 0, 10);
        const back = subtract(from, 3);
        eq("subtracting three days lands on the 7th", back.getDate(), 7);
        eq("the original is untouched", from.getDate(), 10);
        """)


def test_count_dst_transitions(assert_js):
    """Europe/Amsterdam springs forward on 27 March 2022 and back on 30 October 2022."""
    assert_js(
        """
        import { countDSTTransitions } from "/js/daterange-utils.js";
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        eq("the browser was placed in Europe/Amsterdam", tz, "Europe/Amsterdam");
        eq("a week around the spring transition counts one",
           countDSTTransitions(new Date(2022, 2, 24), new Date(2022, 2, 30), 90), 1);
        eq("a week in midsummer counts none",
           countDSTTransitions(new Date(2022, 5, 1), new Date(2022, 5, 8), 90), 0);
        eq("a year counts two",
           countDSTTransitions(new Date(2022, 0, 1), new Date(2022, 11, 31), 90), 2);
        """,
        timezone="Europe/Amsterdam",
    )


def test_count_dst_transitions_where_there_are_none(assert_js):
    """A timezone without daylight saving never reports a transition."""
    assert_js(
        """
        import { countDSTTransitions } from "/js/daterange-utils.js";
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        // Browsers may report either spelling of this zone.
        check("the browser was placed in Asia/Kolkata", ["Asia/Kolkata", "Asia/Calcutta"].includes(tz), tz);
        eq("a whole year counts none",
           countDSTTransitions(new Date(2022, 0, 1), new Date(2022, 11, 31), 90), 0);
        """,
        timezone="Asia/Kolkata",
    )


def test_this_month(assert_js):
    assert_js("""
        import { thisMonth } from "/js/daterange-utils.js";
        const [first, last] = thisMonth(new Date(2022, 1, 15));
        eq("the month starts on the 1st", [first.getMonth(), first.getDate()], [1, 1]);
        eq("and ends on its last day", [last.getMonth(), last.getDate()], [1, 28]);
        const [, leap] = thisMonth(new Date(2024, 1, 3));
        eq("February of a leap year ends on the 29th", leap.getDate(), 29);
        const [, december] = thisMonth(new Date(2022, 11, 31));
        eq("December ends in the same year", [december.getFullYear(), december.getDate()], [2022, 31]);
        """)


def test_last_n_months(assert_js):
    assert_js("""
        import { lastNMonths } from "/js/daterange-utils.js";
        const span = (date, n) => lastNMonths(date, n).map((d) => [d.getFullYear(), d.getMonth() + 1, d.getDate()]);
        eq("one month is the current month", span(new Date(2022, 2, 15), 1), [[2022, 3, 1], [2022, 3, 31]]);
        eq("three months run back to the 1st of two months earlier",
           span(new Date(2022, 2, 31), 3), [[2022, 1, 1], [2022, 3, 31]]);
        eq("a span can cross into the previous year", span(new Date(2022, 1, 10), 3), [[2021, 12, 1], [2022, 2, 28]]);
        """)


def test_offset_between_timezones(assert_js):
    """The result follows getTimezoneOffset's sign convention: positive means the second zone is further west."""
    assert_js("""
        import { getOffsetBetweenTimezonesForDate } from "/js/daterange-utils.js";
        const winter = new Date(Date.UTC(2022, 0, 15, 12));
        const summer = new Date(Date.UTC(2022, 6, 15, 12));
        eq("Amsterdam is an hour ahead of UTC in winter",
           getOffsetBetweenTimezonesForDate(winter, "UTC", "Europe/Amsterdam"), -60);
        eq("and two hours in summer", getOffsetBetweenTimezonesForDate(summer, "UTC", "Europe/Amsterdam"), -120);
        eq("the order of the zones flips the sign",
           getOffsetBetweenTimezonesForDate(winter, "Europe/Amsterdam", "UTC"), 60);
        eq("offsets need not be whole hours", getOffsetBetweenTimezonesForDate(winter, "UTC", "Asia/Kolkata"), -330);
        eq("New York is behind Amsterdam", getOffsetBetweenTimezonesForDate(winter, "Europe/Amsterdam", "America/New_York"), 360);
        const midnight = new Date(Date.UTC(2022, 0, 15));
        eq("midnight is not mistaken for the end of the day",
           getOffsetBetweenTimezonesForDate(midnight, "UTC", "Europe/Amsterdam"), -60);
        """)


def test_simulation_ranges_for_hourly_data(assert_js):
    assert_js(
        """
        import { computeSimulationRanges } from "/js/daterange-utils.js";
        const ymd = (d) => [d.getFullYear(), d.getMonth() + 1, d.getDate()];
        const describe = (ranges) => Object.fromEntries(
            Object.entries(ranges).map(([label, [start, end]]) => [label, [ymd(start), ymd(end)]]));

        // Wednesday 5 to Thursday 6 January 2022
        const short = describe(computeSimulationRanges(new Date(2022, 0, 5), new Date(2022, 0, 6), "hour"));
        eq("less than a week can move by a day or grow to its week", Object.keys(short), ["⇐ day", "Whole week", "day ⇒"]);
        eq("its week runs Monday to Sunday", short["Whole week"], [[2022, 1, 3], [2022, 1, 9]]);
        eq("a day back", short["⇐ day"], [[2022, 1, 4], [2022, 1, 5]]);

        const week = describe(computeSimulationRanges(new Date(2022, 0, 3), new Date(2022, 0, 9), "hour"));
        eq("a week can move by days and weeks, or shrink to a day",
           Object.keys(week), ["⇐ week", "⇐ day", "One day", "day ⇒", "week ⇒"]);
        eq("shrinking keeps the first day", week["One day"], [[2022, 1, 3], [2022, 1, 3]]);
        eq("a week on", week["week ⇒"], [[2022, 1, 10], [2022, 1, 16]]);
        """,
        timezone="Europe/Amsterdam",
    )


def test_simulation_ranges_for_daily_data(assert_js):
    assert_js(
        """
        import { computeSimulationRanges } from "/js/daterange-utils.js";
        const ymd = (d) => [d.getFullYear(), d.getMonth() + 1, d.getDate()];
        const describe = (ranges) => Object.fromEntries(
            Object.entries(ranges).map(([label, [start, end]]) => [label, [ymd(start), ymd(end)]]));

        const week = describe(computeSimulationRanges(new Date(2022, 0, 3), new Date(2022, 0, 9), "day"));
        eq("a week of daily data moves by weeks, or grows to its month", Object.keys(week), ["⇐ week", "Whole month", "week ⇒"]);
        eq("its month", week["Whole month"], [[2022, 1, 1], [2022, 1, 31]]);

        // Thursday 6 to Wednesday 26 January 2022
        const weeks = describe(computeSimulationRanges(new Date(2022, 0, 6), new Date(2022, 0, 26), "day"));
        eq("several weeks move by weeks and months, or shrink to a week",
           Object.keys(weeks), ["⇐ month", "⇐ week", "One week", "week ⇒", "month ⇒"]);
        eq("shrinking picks the first full week", weeks["One week"], [[2022, 1, 10], [2022, 1, 16]]);
        eq("a month back is the whole previous month", weeks["⇐ month"], [[2021, 12, 1], [2021, 12, 31]]);
        eq("a month on is the whole next month", weeks["month ⇒"], [[2022, 2, 1], [2022, 2, 28]]);

        const days = describe(computeSimulationRanges(new Date(2022, 0, 5), new Date(2022, 0, 6), "day"));
        eq("less than a week of daily data behaves as for hourly data", Object.keys(days), ["⇐ day", "Whole week", "day ⇒"]);

        let error = null;
        try { computeSimulationRanges(new Date(2022, 0, 5), new Date(2022, 0, 6), "minute"); } catch (e) { error = e.message; }
        eq("other resolutions are refused", error, "Unsupported minimum resolution: minute");
        """,
        timezone="Europe/Amsterdam",
    )


def test_simulation_ranges_step_whole_days_across_dst(assert_js):
    """Stepping a day across the spring transition lands on midnight, not on 1 am or 11 pm."""
    assert_js(
        """
        import { computeSimulationRanges } from "/js/daterange-utils.js";
        const ranges = computeSimulationRanges(new Date(2022, 2, 26), new Date(2022, 2, 27), "hour");
        const [start, end] = ranges["day ⇒"];
        eq("the next day starts at midnight", [start.getDate(), start.getHours()], [27, 0]);
        eq("and ends at midnight", [end.getDate(), end.getHours()], [28, 0]);
        """,
        timezone="Europe/Amsterdam",
    )


def test_encode_url_query(assert_js):
    assert_js("""
        import { encodeUrlQuery } from "/js/daterange-utils.js";
        eq("the plus sign of a UTC offset is kept, encoded",
           encodeUrlQuery("path?date=2025-06-16T00:00:00+02:00"), "path?date=2025-06-16T00%3A00%3A00%2B02%3A00");
        const encoded = encodeUrlQuery("path?event_starts_after=2025-06-16T00:00:00+02:00&chart_type=bar_chart");
        eq("the server reads back the same offset",
           new URLSearchParams(encoded.split("?")[1]).get("event_starts_after"), "2025-06-16T00:00:00+02:00");
        eq("a URL without a query is left alone", encodeUrlQuery("path"), "path");
        eq("already encoded values are not encoded twice",
           encodeUrlQuery("path?date=2025-06-16T00%3A00%3A00%2B02%3A00"), "path?date=2025-06-16T00%3A00%3A00%2B02%3A00");
        eq("other parameters survive", encodeUrlQuery("path?a=1&b=x y"), "path?a=1&b=x+y");
        """)
