from flask import url_for
import pytest
from isodate import parse_datetime, parse_duration

from rq.job import Job

from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.data.services.scheduling import (
    handle_scheduling_exception,
    get_data_source_for_job,
)


@pytest.mark.parametrize(
    "message, asset_name",
    [
        (message_for_trigger_schedule(), "Test battery"),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_asset_trigger_and_get_schedule(
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
        "consumption-price": {"sensor": price_sensor_id},
        "production-price": {"sensor": price_sensor_id},
        "site-power-capacity": "1 TW",  # should be big enough to avoid any infeasibilities
    }

    # trigger a schedule through the /assets/<id>/schedules/trigger [POST] api endpoint
    assert len(app.queues["scheduling"]) == 0

    sensor = (
        Sensor.query.filter(Sensor.name == "power")
        .join(GenericAsset, GenericAsset.id == Sensor.generic_asset_id)
        .filter(GenericAsset.name == asset_name)
        .one_or_none()
    )
    message["flex-model"]["sensor"] = sensor.id

    # Convert the flex-model to a multi-asset flex-model
    message["flex-model"] = [
        message["flex-model"],
    ]

    with app.test_client() as client:
        print(message)
        print(message["flex-model"])
        trigger_schedule_response = client.post(
            url_for("AssetAPI:trigger_schedule", id=sensor.generic_asset.id),
            json=message,
        )
        print("Server responded with:\n%s" % trigger_schedule_response.json)
        assert trigger_schedule_response.status_code == 200
        job_id = trigger_schedule_response.json["schedule"]

    # look for scheduling jobs in queue
    scheduled_jobs = app.queues["scheduling"].jobs
    deferred_job_ids = app.queues["scheduling"].deferred_job_registry.get_job_ids()
    assert len(scheduled_jobs) == len(
        message["flex-model"]
    ), "a scheduling job should be made for each sensor flex model"
    assert (
        len(deferred_job_ids) == 1
    ), "only 1 job should be triggered when the last scheduling job is done"
    scheduling_job = scheduled_jobs[0]
    done_job_id = deferred_job_ids[0]
    print(scheduling_job.kwargs)
    assert scheduling_job.kwargs["asset_or_sensor"]["id"] == sensor.id
    assert scheduling_job.kwargs["start"] == parse_datetime(message["start"])
    assert done_job_id == job_id

    # process the scheduling queue
    work_on_rq(app.queues["scheduling"], exc_handler=handle_scheduling_exception)
    assert (
        Job.fetch(job_id, connection=app.queues["scheduling"].connection).is_finished
        is True
    )

    # Derive some expectations from the POSTed message
    resolution = sensor.event_resolution
    expected_length_of_schedule = parse_duration(message["duration"]) / resolution

    # check results are in the database

    # First, make sure the scheduler data source is now there
    scheduling_job.refresh()  # catch meta info that was added on this very instance
    scheduler_source = get_data_source_for_job(scheduling_job)
    assert scheduler_source is not None

    # try to retrieve the schedule for each sensor through the /sensors/<id>/schedules/<job_id> [GET] api endpoint
    for flex_model in message["flex-model"]:
        sensor_id = flex_model["sensor"]
        get_schedule_response = client.get(
            url_for(
                "SensorAPI:get_schedule", id=sensor_id, uuid=scheduling_job.id
            ),  # todo: use (last?) job_id from trigger response
            query_string={"duration": "PT48H"},
        )
        print("Server responded with:\n%s" % get_schedule_response.json)
        assert get_schedule_response.status_code == 200
        # assert get_schedule_response.json["type"] == "GetDeviceMessageResponse"
        assert len(get_schedule_response.json["values"]) == expected_length_of_schedule
