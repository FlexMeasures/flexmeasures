"""Tests for flexmeasures/ui/static/js/sensor-status-utils.js."""


def test_every_sensor_that_answers_is_reported(assert_js):
    assert_js("""
        import { fetchSensorStatuses } from "/js/sensor-status-utils.js";
        const statuses = await fetchSensorStatuses(
            [1, 2, 3],
            (sensorId) => Promise.resolve({sensors_data: [{id: sensorId}]}),
        );
        eq("each sensor contributes its status", statuses, [{id: 1}, {id: 2}, {id: 3}]);
        """)


def test_a_sensor_may_report_several_statuses(assert_js):
    """A sensor reports one status per data source type that stored data on it."""
    assert_js("""
        import { fetchSensorStatuses } from "/js/sensor-status-utils.js";
        const statuses = await fetchSensorStatuses(
            [1, 2],
            (sensorId) => Promise.resolve({sensors_data: [
                {id: sensorId, source_type: "user"},
                {id: sensorId, source_type: "forecaster"},
            ]}),
        );
        eq("every source type of every sensor is reported", statuses.length, 4);
        """)


def test_a_failing_sensor_does_not_hide_the_others(assert_js):
    """Regression test: the status page showed only a subset of the sensors it had asked about.

    A failing request used to be counted twice, so the table was handed over before the slower requests came back,
    and which sensors made it onto the page depended on which ones answered first.
    """
    assert_js("""
        import { fetchSensorStatuses } from "/js/sensor-status-utils.js";
        const failed = [];
        const statuses = await fetchSensorStatuses(
            [1, 2, 3, 4, 5],
            // The two failing sensors answer at once, while the others take their time,
            // which is the order that used to cut the collection short.
            (sensorId) => sensorId % 2 === 0
                ? Promise.reject(new Error("no such sensor"))
                : new Promise((resolve) => setTimeout(() => resolve({sensors_data: [{id: sensorId}]}), 20)),
            (sensorId) => failed.push(sensorId),
        );
        eq("the sensors that answered are all reported", statuses, [{id: 1}, {id: 3}, {id: 5}]);
        eq("the sensors that did not answer are reported to the caller", failed, [2, 4]);
        """)


def test_a_fetcher_that_throws_is_treated_as_a_failed_sensor(assert_js):
    assert_js("""
        import { fetchSensorStatuses } from "/js/sensor-status-utils.js";
        const statuses = await fetchSensorStatuses(
            [1, 2],
            (sensorId) => {
                if (sensorId === 1) throw new Error("could not even ask");
                return Promise.resolve({sensors_data: [{id: sensorId}]});
            },
        );
        eq("the sensor that could be asked is still reported", statuses, [{id: 2}]);
        """)


def test_a_response_without_statuses_contributes_nothing(assert_js):
    assert_js("""
        import { fetchSensorStatuses } from "/js/sensor-status-utils.js";
        const statuses = await fetchSensorStatuses(
            [1, 2, 3],
            (sensorId) => Promise.resolve(sensorId === 2 ? {} : {sensors_data: [{id: sensorId}]}),
        );
        eq("a response without sensors_data is skipped", statuses, [{id: 1}, {id: 3}]);
        """)


def test_no_sensors_means_no_statuses(assert_js):
    assert_js("""
        import { fetchSensorStatuses } from "/js/sensor-status-utils.js";
        const statuses = await fetchSensorStatuses([], () => Promise.reject(new Error("never asked")));
        eq("nothing to ask about yields nothing", statuses, []);
        """)
