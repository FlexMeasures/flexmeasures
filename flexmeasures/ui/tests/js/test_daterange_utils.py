"""Tests for flexmeasures/ui/static/js/daterange-utils.js."""


def test_to_iso_string_with_offset_keeps_the_instant(assert_js):
    """Formatting a date with a local offset must not move it in time.

    The KPI window is sent to the API through this function,
    so an instant that shifts by the local offset asks for the wrong days.
    """
    assert_js(
        """
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
        """
    )


def test_subtract_counts_whole_days(assert_js):
    assert_js(
        """
        import { subtract } from "/js/daterange-utils.js";
        const from = new Date(2022, 0, 10);
        const back = subtract(from, 3);
        eq("subtracting three days lands on the 7th", back.getDate(), 7);
        eq("the original is untouched", from.getDate(), 10);
        """
    )


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
