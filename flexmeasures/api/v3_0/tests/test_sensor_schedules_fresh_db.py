from flask import url_for
import pytest
from isodate import parse_datetime, parse_duration

import pandas as pd
from rq.job import Job

from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.data.services.scheduling import (
    handle_scheduling_exception,
    get_data_source_for_job,
)
from flexmeasures.utils.calculations import integrate_time_series


@pytest.mark.parametrize(
    "message, asset_name",
    [
        (message_for_trigger_schedule(), "Test battery"),
        (message_for_trigger_schedule(with_targets=True), "Test charging station"),
        (
            message_for_trigger_schedule(with_targets=True, use_time_window=True),
            "Test charging station",
        ),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_and_get_schedule(
    app,
    add_market_prices_fresh_db,
    add_battery_assets_fresh_db,
    battery_soc_sensor_fresh_db,
    add_charging_station_assets_fresh_db,
    keep_scheduling_queue_empty,
    message,
    asset_name,
    requesting_user,
):  # noqa: C901
    # Include the price sensor and site-power-capacity in the flex-context explicitly, to test deserialization
    price_sensor_id = add_market_prices_fresh_db["epex_da"].id
    message["flex-context"] = {
        "consumption-price-sensor": price_sensor_id,
        "production-price-sensor": price_sensor_id,
        "site-power-capacity": "1 TW",  # should be big enough to avoid any infeasibilities
    }

    # trigger a schedule through the /sensors/<id>/schedules/trigger [POST] api endpoint
    assert len(app.queues["scheduling"]) == 0

    sensor = (
        Sensor.query.filter(Sensor.name == "power")
        .join(GenericAsset)
        .filter(GenericAsset.id == Sensor.generic_asset_id)
        .filter(GenericAsset.name == asset_name)
        .one_or_none()
    )
    with app.test_client() as client:
        trigger_schedule_response = client.post(
            url_for("SensorAPI:trigger_schedule", id=sensor.id),
            json=message,
        )
        print("Server responded with:\n%s" % trigger_schedule_response.json)
        assert trigger_schedule_response.status_code == 200
        job_id = trigger_schedule_response.json["schedule"]

    # look for scheduling jobs in queue
    assert (
        len(app.queues["scheduling"]) == 1
    )  # only 1 schedule should be made for 1 asset
    job = app.queues["scheduling"].jobs[0]
    print(job.kwargs)
    assert job.kwargs["asset_or_sensor"]["id"] == sensor.id
    assert job.kwargs["start"] == parse_datetime(message["start"])
    assert job.id == job_id

    # process the scheduling queue
    work_on_rq(app.queues["scheduling"], exc_handler=handle_scheduling_exception)
    assert (
        Job.fetch(job_id, connection=app.queues["scheduling"].connection).is_finished
        is True
    )

    # Derive some expectations from the POSTed message
    if "flex-model" not in message:
        start_soc = message["soc-at-start"] / 1000  # in MWh
        roundtrip_efficiency = (
            float(message["roundtrip-efficiency"].replace("%", "")) / 100.0
        )
        storage_efficiency = (
            float(message["storage-efficiency"].replace("%", "")) / 100.0
        )
        soc_targets = message.get("soc-targets")
    else:
        start_soc = message["flex-model"]["soc-at-start"] / 1000  # in MWh
        roundtrip_efficiency = (
            float(message["flex-model"]["roundtrip-efficiency"].replace("%", ""))
            / 100.0
        )
        storage_efficiency = (
            float(message["flex-model"]["storage-efficiency"].replace("%", "")) / 100.0
        )
        soc_targets = message["flex-model"].get("soc-targets")
    resolution = sensor.event_resolution
    if soc_targets:
        # Schedule length may be extended to accommodate targets that lie beyond the schedule's end
        max_target_datetime = max(
            [
                parse_datetime(soc_target.get("datetime", soc_target.get("end")))
                for soc_target in soc_targets
            ]
        )
        expected_length_of_schedule = (
            max(
                parse_duration(message["duration"]),
                max_target_datetime - parse_datetime(message["start"]),
            )
            / resolution
        )
    else:
        expected_length_of_schedule = parse_duration(message["duration"]) / resolution

    # check results are in the database

    # First, make sure the scheduler data source is now there
    job.refresh()  # catch meta info that was added on this very instance
    scheduler_source = get_data_source_for_job(job)
    assert scheduler_source is not None

    # Then, check if the data was created
    power_values = (
        TimedBelief.query.filter(TimedBelief.sensor_id == sensor.id)
        .filter(TimedBelief.source_id == scheduler_source.id)
        .all()
    )
    consumption_schedule = pd.Series(
        [-v.event_value for v in power_values],
        index=pd.DatetimeIndex([v.event_start for v in power_values], freq=resolution),
    )  # For consumption schedules, positive values denote consumption. For the db, consumption is negative
    assert len(consumption_schedule) == expected_length_of_schedule

    # check targets, if applicable
    if soc_targets:
        soc_schedule = integrate_time_series(
            consumption_schedule,
            start_soc,
            up_efficiency=roundtrip_efficiency**0.5,
            down_efficiency=roundtrip_efficiency**0.5,
            storage_efficiency=storage_efficiency,
            decimal_precision=6,
        )
        print(consumption_schedule)
        print(soc_schedule)
        for target in soc_targets:
            assert (
                soc_schedule[target.get("datetime", target.get("end"))]
                == target["value"] / 1000
            )

    # try to retrieve the schedule through the /sensors/<id>/schedules/<job_id> [GET] api endpoint
    get_schedule_response = client.get(
        url_for("SensorAPI:get_schedule", id=sensor.id, uuid=job_id),
        query_string={"duration": "PT48H"},
    )
    print("Server responded with:\n%s" % get_schedule_response.json)
    assert get_schedule_response.status_code == 200
    # assert get_schedule_response.json["type"] == "GetDeviceMessageResponse"
    assert len(get_schedule_response.json["values"]) == expected_length_of_schedule

    # Test that a shorter planning horizon yields the same result for the shorter planning horizon
    get_schedule_response_short = client.get(
        url_for("SensorAPI:get_schedule", id=sensor.id, uuid=job_id),
        query_string={"duration": "PT6H"},
    )
    assert (
        get_schedule_response_short.json["values"]
        == get_schedule_response.json["values"][0:24]
    )

    # Test that a much longer planning horizon yields the same result (when there are only 2 days of prices)
    get_schedule_response_long = client.get(
        url_for("SensorAPI:get_schedule", id=sensor.id, uuid=job_id),
        query_string={"duration": "PT1000H"},
    )
    assert (
        get_schedule_response_long.json["values"][0:192]
        == get_schedule_response.json["values"]
    )

    # Check whether the soc-at-start was persisted as an asset attribute
    assert sensor.generic_asset.get_attribute("soc_in_mwh") == start_soc
