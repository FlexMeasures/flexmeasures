"""Tests for flexmeasures/ui/static/js/data-utils.js."""


def test_get_unique_values_by_nested_key(assert_js):
    assert_js("""
        import { getUniqueValues } from "/js/data-utils.js";
        const data = [
            {id: 1, source: {id: 4}},
            {id: 2, source: {id: 4}},
            {id: 3, source: {id: 5}},
        ];
        eq("repeated source ids collapse", getUniqueValues(data, "source.id"), [4, 5]);
        eq("an empty list yields nothing", getUniqueValues([], "source.id"), []);
        """)


def test_get_unique_values_survives_a_falsy_entry(assert_js):
    """The loop condition treats a falsy element as the end of the list."""
    assert_js("""
        import { getUniqueValues } from "/js/data-utils.js";
        const data = [{source: {id: 4}}, null, {source: {id: 5}}];
        const values = getUniqueValues(data, "source.id");
        check("values after a null entry are still seen", values.includes(5), JSON.stringify(values));
        eq("the missing record contributes nothing", values, [4, 5]);
        """)


def test_convert_to_csv(assert_js):
    assert_js("""
        import { convertToCSV } from "/js/data-utils.js";
        eq("no rows means no csv", convertToCSV([]), "");
        const csv = convertToCSV([{event_value: 1.5, belief_horizon: 3600000}]);
        check("the header names the columns", csv.includes("event_value,belief_horizon"), csv);
        check("a one hour horizon is written as PT1H", csv.includes("PT1H"), csv);
        const zero = convertToCSV([{event_value: 1, belief_horizon: 0}]);
        check("a zero horizon is written as PT0H", zero.includes("PT0H"), zero);
        """)


def test_get_unique_values_handles_names_that_exist_on_every_object(assert_js):
    """Source names come from user data, so they may collide with Object prototype members."""
    assert_js("""
        import { getUniqueValues } from "/js/data-utils.js";
        const data = [{source: {name: "constructor"}}, {source: {name: "toString"}}, {source: {name: "solar"}}];
        const values = getUniqueValues(data, "source.name");
        eq("every distinct name is returned", values.sort(), ["constructor", "solar", "toString"].sort());
        """)


def test_get_unique_values_ignores_records_without_the_key(assert_js):
    """A record with no source is not a source.

    checkSourceMasking counts these to decide whether data is being masked,
    so an absent value must not be counted as one more source.
    """
    assert_js("""
        import { getUniqueValues } from "/js/data-utils.js";
        eq("a record without a source is not counted",
           getUniqueValues([{source: {id: 4}}, {event_value: 1}], "source.id"), [4]);
        eq("only records without the key means nothing to report",
           getUniqueValues([{event_value: 1}], "source.id"), []);
        """)


def test_convert_to_csv_writes_timestamps_in_local_time(assert_js):
    assert_js(
        """
        import { convertToCSV } from "/js/data-utils.js";
        const ms = Date.UTC(2022, 6, 1, 10);
        const csv = convertToCSV([{event_start: ms, belief_time: ms, event_value: 3}]);
        const [header, row] = csv.replace("data:text/csv;charset=utf-8,", "").split("\\n");
        eq("the csv is a data URL", csv.startsWith("data:text/csv;charset=utf-8,"), true);
        eq("the header lists the columns in order", header, "event_start,belief_time,event_value");
        eq("timestamps are written with the viewer's offset",
           row, "2022-07-01T12:00:00.000+02:00,2022-07-01T12:00:00.000+02:00,3");
        """,
        timezone="Europe/Amsterdam",
    )


def test_convert_to_csv_writes_horizons_as_durations(assert_js):
    assert_js("""
        import { convertToCSV } from "/js/data-utils.js";
        const horizon = (ms) => convertToCSV([{belief_horizon: ms}]).split("\\n")[1];
        eq("hours, minutes and seconds", horizon(3600000 + 2 * 60000 + 3000), "PT1H2M3S");
        eq("a horizon of more than a day is still counted in hours", horizon(90000000), "PT25H");
        eq("a negative horizon (a belief formed after the fact) keeps its sign", horizon(-1800000), "-PT30M");
        """)


def test_convert_to_csv_describes_nested_objects(assert_js):
    assert_js("""
        import { convertToCSV } from "/js/data-utils.js";
        const csv = convertToCSV([
            {sensor: {id: 1, description: "power (kW)"}, source: {id: 9}, event_value: null},
        ]);
        eq("a sensor or source is written as its description, or left empty",
           csv.split("\\n")[1], "power (kW),,");
        """)
