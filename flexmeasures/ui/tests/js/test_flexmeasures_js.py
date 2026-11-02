"""Tests for the helpers in flexmeasures/ui/static/js/flexmeasures.js.

That file is a classic script rather than a module:
every page loads it, and its functions become globals.
It expects jQuery, Vega and a currency map on the page, so the tests put stand-ins there first.
"""

# Loads flexmeasures.js the way base.html does, with just enough of its dependencies to run its top level.
LOAD_FLEXMEASURES_JS = """
const chain = new Proxy(function () {}, {get: () => chain, apply: () => chain});
window.$ = chain;
window.vegaFormatters = {};
window.vega = {expressionFunction: (name, formatter) => { window.vegaFormatters[name] = formatter; }};
window.currencySymbolMap = {EUR: "€", USD: "$", KRW: "₩"};
await new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/js/flexmeasures.js";
    script.onload = resolve;
    script.onerror = () => reject(new Error("could not load flexmeasures.js"));
    document.head.append(script);
});
"""


def test_number_with_commas(assert_js):
    assert_js(LOAD_FLEXMEASURES_JS + """
        eq("thousands are separated", numberWithCommas(1234567), "1,234,567");
        eq("decimals are left alone", numberWithCommas(1234.5678), "1,234.5678");
        eq("small numbers are unchanged", numberWithCommas(999), "999");
        eq("negative numbers too", numberWithCommas(-1234), "-1,234");
        """)


def test_currency_codes_become_symbols(assert_js):
    assert_js(LOAD_FLEXMEASURES_JS + """
        eq("a currency code in a unit is replaced", convertCurrencyCodeToSymbol("EUR/MWh"), "€/MWh");
        eq("every code is replaced", replaceMultiple("EUR or USD", currencySymbolMap), "€ or $");
        eq("units without currency are unchanged", convertCurrencyCodeToSymbol("kW"), "kW");
        """)


def test_time_ago(assert_js):
    assert_js(LOAD_FLEXMEASURES_JS + """
        const ago = (seconds) => getTimeAgo(Date.now() - seconds * 1000);
        eq("seconds", ago(30), "30 seconds ago");
        eq("one minute", ago(60), "1 minute ago");
        eq("minutes", ago(125), "2 minutes ago");
        eq("one hour", ago(3600), "1 hour ago");
        eq("hours", ago(5 * 3600 + 10), "5 hours ago");
        eq("one day", ago(86400), "1 day ago");
        eq("days", ago(3 * 86400), "3 days ago");
        """)


def test_human_friendly_delta_for_past_moments(assert_js):
    assert_js(LOAD_FLEXMEASURES_JS + """
        const ago = (seconds) => getHumanFriendlyDeltaOrTimeStr(new Date(Date.now() - seconds * 1000).toISOString());
        eq("a moment ago", ago(2), "just now");
        eq("seconds", ago(30), "30 seconds ago");
        eq("one minute", ago(90), "1 minute ago");
        eq("minutes", ago(20 * 60), "20 minutes ago");
        eq("one hour", ago(3600 + 60), "1 hour ago");
        eq("hours", ago(5 * 3600), "5 hours ago");
        eq("a day", ago(30 * 3600), "yesterday");
        eq("days", ago(3 * 86400 + 60), "3 days ago");
        const old = new Date(Date.UTC(2020, 4, 22, 10));
        check("a week or more shows the date",
              getHumanFriendlyDeltaOrTimeStr(old.toISOString()).includes("2020"),
              getHumanFriendlyDeltaOrTimeStr(old.toISOString()));
        check("optionally without the time",
              !getHumanFriendlyDeltaOrTimeStr(old.toISOString(), {dateOnlyForOlder: true}).includes("@"),
              getHumanFriendlyDeltaOrTimeStr(old.toISOString(), {dateOnlyForOlder: true}));
        """)


def test_humanize_iso_duration(assert_js):
    assert_js(LOAD_FLEXMEASURES_JS + """
        eq("hours", humanizeIsoDuration("PT1H"), "1 hour");
        eq("plural", humanizeIsoDuration("PT15M"), "15 minutes");
        eq("several units", humanizeIsoDuration("P1DT2H30M"), "1 day 2 hours 30 minutes");
        eq("weeks", humanizeIsoDuration("P2W"), "2 weeks");
        eq("fractional seconds", humanizeIsoDuration("PT1.5S"), "1.5 seconds");
        eq("months are not minutes", humanizeIsoDuration("P1M"), "1 month");
        eq("anything else is shown as is", humanizeIsoDuration("every hour"), "every hour");
        eq("non-strings are passed through", humanizeIsoDuration(3600), 3600);
        """)


def test_unpack_data(assert_js):
    """The stats endpoint sends each source's statistics as a list of key-value pairs."""
    assert_js(LOAD_FLEXMEASURES_JS + """
        const errors = [];
        console.error = (...args) => errors.push(args[0]);
        eq("pairs become objects",
           unpackData({"All sources": [["Min value", 1], ["Max value", 5]]}),
           {"All sources": {"Min value": 1, "Max value": 5}});
        eq("anything else is kept, and reported",
           unpackData({odd: "not pairs"}), {odd: "not pairs"});
        eq("once", errors.length, 1);
        """)


def test_latest_belief_name(assert_js):
    assert_js(LOAD_FLEXMEASURES_JS + """
        const stats = {
            "forecaster (ID: 3)": {"Last recorded": "2024-01-02T00:00:00+00:00"},
            "meter (ID: 1)": {"Last recorded": "2024-01-03T00:00:00+00:00"},
            "old (ID: 2)": {"Last recorded": "2023-01-01T00:00:00+00:00"},
        };
        eq("the source that recorded most recently is picked", getLatestBeliefName(stats), "meter (ID: 1)");
        eq("no sources, no pick", getLatestBeliefName({}), null);
        """)


def test_source_id_from_key(assert_js):
    assert_js(LOAD_FLEXMEASURES_JS + """
        eq("the id is read from the end of the key", sourceIdFromKey("forecaster (ID: 12)"), "12");
        eq("an id elsewhere in the name does not count", sourceIdFromKey("the (ID: 12) forecaster"), null);
        eq("the key covering every source has no id", sourceIdFromKey(ALL_SOURCES_KEY), null);
        """)


def test_timezone_format(assert_js):
    """The Vega formatter shows the viewer's offset, followed by the zone the chart is in."""
    assert_js(
        LOAD_FLEXMEASURES_JS + """
        const format = vegaFormatters["timezoneFormat"];
        eq("summer time", format(new Date(2022, 6, 1), ["Europe/Amsterdam"]), "+02:00 (Europe/Amsterdam)");
        eq("winter time", format(new Date(2022, 0, 1), ["Europe/Amsterdam"]), "+01:00 (Europe/Amsterdam)");
        """,
        timezone="Europe/Amsterdam",
    )
    assert_js(
        LOAD_FLEXMEASURES_JS + """
        const format = vegaFormatters["timezoneFormat"];
        eq("west of UTC, and not a whole hour", format(new Date(2022, 0, 1), ["America/St_Johns"]), "-03:30 (America/St_Johns)");
        """,
        timezone="America/St_Johns",
    )
