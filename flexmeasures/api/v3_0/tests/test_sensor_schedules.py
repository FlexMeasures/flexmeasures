from flask import url_for
import pytest
from datetime import timedelta
from isodate import parse_datetime

import pandas as pd
from rq.job import Job

from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v1_3.tests.utils import message_for_get_device_message
from flexmeasures.api.v3_0.tests.utils import message_for_post_udi_event
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.data.services.scheduling import handle_scheduling_exception
from flexmeasures.utils.calculations import integrate_time_series


@pytest.mark.parametrize(
    "message, asset_name",
    [
        (message_for_post_udi_event(), "Test battery"),
        (message_for_post_udi_event(targets=True), "Test charging station"),
    ],
)
def test_trigger_and_get_schedule(
    app,
    add_market_prices,
    add_battery_assets,
    battery_soc_sensor,
    add_charging_station_assets,
    message,
    asset_name,
):
    # trigger a schedule through the /sensors/<id>/schedules/trigger [POST] api endpoint
    message["roundtrip-efficiency"] = 0.98
    message["soc-min"] = 0
    message["soc-max"] = 25
    with app.test_client() as client:
        sensor = Sensor.query.filter(Sensor.name == asset_name).one_or_none()
        message["soc-sensor"] = f"ea1.2018-06.localhost:fm1.{battery_soc_sensor.id}"
        auth_token = get_auth_token(client, "test_prosumer_user@seita.nl", "testtest")
        trigger_schedule_response = client.post(
            url_for("SensorAPI:trigger_schedule", id=sensor.id),
            json=message,
            headers={"Authorization": auth_token},
        )
        print("Server responded with:\n%s" % trigger_schedule_response.json)
        assert trigger_schedule_response.status_code == 200
        job_id = trigger_schedule_response.json["schedule"]

    # look for scheduling jobs in queue
    assert (
        len(app.queues["scheduling"]) == 1
    )  # only 1 schedule should be made for 1 asset
    job = app.queues["scheduling"].jobs[0]
    assert job.kwargs["sensor_id"] == sensor.id
    assert job.kwargs["start"] == parse_datetime(message["start"])
    assert job.id == job_id

    # process the scheduling queue
    work_on_rq(app.queues["scheduling"], exc_handler=handle_scheduling_exception)
    assert (
        Job.fetch(job_id, connection=app.queues["scheduling"].connection).is_finished
        is True
    )

    # check results are in the database
    resolution = timedelta(minutes=15)
    scheduler_source = DataSource.query.filter_by(
        name="Seita", type="scheduling script"
    ).one_or_none()
    assert (
        scheduler_source is not None
    )  # Make sure the scheduler data source is now there
    power_values = (
        TimedBelief.query.filter(TimedBelief.sensor_id == sensor.id)
        .filter(TimedBelief.source_id == scheduler_source.id)
        .all()
    )
    consumption_schedule = pd.Series(
        [-v.event_value for v in power_values],
        index=pd.DatetimeIndex([v.event_start for v in power_values], freq=resolution),
    )  # For consumption schedules, positive values denote consumption. For the db, consumption is negative
    assert (
        len(consumption_schedule)
        == app.config.get("FLEXMEASURES_PLANNING_HORIZON") / resolution
    )

    # check targets, if applicable
    if "targets" in message:
        start_soc = message["soc-at-start"] / 1000  # in MWh
        soc_schedule = integrate_time_series(consumption_schedule, start_soc, 6)
        print(consumption_schedule)
        print(soc_schedule)
        for target in message["targets"]:
            assert soc_schedule[target["datetime"]] == target["soc-target"] / 1000

    # try to retrieve the schedule through the /sensors/<id>/schedules/<job_id> [GET] api endpoint
    get_schedule_message = message_for_get_device_message(
        targets="soc-targets" in message
    )
    del get_schedule_message["type"]
    auth_token = get_auth_token(client, "test_prosumer_user@seita.nl", "testtest")
    get_schedule_response = client.get(
        url_for("SensorAPI:get_schedule", id=sensor.id, uuid=job_id),
        query_string=get_schedule_message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_schedule_response.json)
    assert get_schedule_response.status_code == 200
    # assert get_schedule_response.json["type"] == "GetDeviceMessageResponse"
    assert len(get_schedule_response.json["values"]) == 192

    # Test that a shorter planning horizon yields the same result for the shorter planning horizon
    get_schedule_message["duration"] = "PT6H"
    get_schedule_response_short = client.get(
        url_for("SensorAPI:get_schedule", id=sensor.id, uuid=job_id),
        query_string=get_schedule_message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    assert (
        get_schedule_response_short.json["values"]
        == get_schedule_response.json["values"][0:24]
    )

    # Test that a much longer planning horizon yields the same result (when there are only 2 days of prices)
    get_schedule_message["duration"] = "PT1000H"
    get_schedule_response_long = client.get(
        url_for("SensorAPI:get_schedule", id=sensor.id, uuid=job_id),
        query_string=get_schedule_message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    assert (
        get_schedule_response_long.json["values"][0:192]
        == get_schedule_response.json["values"]
    )
