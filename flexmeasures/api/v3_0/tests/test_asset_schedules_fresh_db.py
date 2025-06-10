from flask import url_for
import pytest
from isodate import parse_datetime, parse_duration

import pandas as pd
from rq.job import Job

from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.data.services.scheduling import (
    handle_scheduling_exception,
    get_data_source_for_job,
)
from flexmeasures.data.services.utils import sort_jobs


@pytest.mark.parametrize(
    "message_without_targets, message_with_targets, asset_name",
    [
        (
            message_for_trigger_schedule(),
            message_for_trigger_schedule(with_targets=True),
            "Test battery",
        ),
    ],
)
@pytest.mark.parametrize("sequential", [True, False])
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_asset_trigger_and_get_schedule(
    app,
    add_market_prices_fresh_db,
    setup_roles_users_fresh_db,
    add_charging_station_assets_fresh_db,
    keep_scheduling_queue_empty,
    message_without_targets,
    message_with_targets,
    asset_name,
    sequential,
    requesting_user,
):  # noqa: C901
    # Include the price sensor and site-power-capacity in the flex-context explicitly, to test deserialization
    price_sensor_id = add_market_prices_fresh_db["epex_da"].id
    message_without_targets["flex-context"] = {
        "consumption-price": {"sensor": price_sensor_id},
        "production-price": {"sensor": price_sensor_id},
        "site-power-capacity": "1 TW",  # should be big enough to avoid any infeasibilities
    }

    # Set up flex-model for CP 1
    CP_1_flex_model = message_without_targets["flex-model"].copy()
    bidirectional_charging_station = add_charging_station_assets_fresh_db[
        "Test charging station (bidirectional)"
    ]
    sensor_1 = bidirectional_charging_station.sensors[0]
    assert sensor_1.name == "power", "expecting to schedule a power sensor"

    # Set up flex-model for CP 2
    charging_station = add_charging_station_assets_fresh_db["Test charging station"]
    CP_2_flex_model = message_with_targets["flex-model"].copy()
    sensor_2 = charging_station.sensors[0]
    assert sensor_2.name == "power", "expecting to schedule a power sensor"

    # Convert the two flex-models to a single multi-asset flex-model
    CP_1_flex_model["sensor"] = sensor_1.id
    CP_2_flex_model["sensor"] = sensor_2.id
    message = message_without_targets.copy()
    message["flex-model"] = [
        CP_1_flex_model,
        CP_2_flex_model,
    ]
    message["sequential"] = sequential

    # trigger a schedule through the /assets/<id>/schedules/trigger [POST] api endpoint
    assert len(app.queues["scheduling"]) == 0
    with app.test_client() as client:
        print(message)
        print(message["flex-model"])
        trigger_schedule_response = client.post(
            url_for(
                "AssetAPI:trigger_schedule", id=sensor_1.generic_asset.parent_asset.id
            ),
            json=message,
        )
        print("Server responded with:\n%s" % trigger_schedule_response.json)
        assert trigger_schedule_response.status_code == 200
        job_id = trigger_schedule_response.json["schedule"]

    # look for scheduling jobs in queue
    scheduled_jobs = app.queues["scheduling"].jobs
    deferred_job_ids = app.queues["scheduling"].deferred_job_registry.get_job_ids()
    deferred_jobs = sort_jobs(app.queues["scheduling"], deferred_job_ids)

    assert len(scheduled_jobs) == 1, "one scheduling job should be queued"
    if sequential:
        assert len(deferred_jobs) == len(
            message["flex-model"]
        ), "a scheduling job should be made for each sensor flex model (1 was already queued, but there is also 1 wrap-up job that should be triggered when the last scheduling job is done"
        done_job_id = deferred_jobs[-1].id
    else:
        assert (
            len(deferred_jobs) == 0
        ), "the whole scheduling job is handled as a single job (simultaneous scheduling)"
        done_job_id = scheduled_jobs[0].id
    scheduling_job = scheduled_jobs[0]

    print(scheduling_job.kwargs)
    if sequential:
        assert (
            scheduling_job.kwargs["asset_or_sensor"]["id"] == sensor_1.id
        ), "first queued job is for scheduling the first sensor"
    else:
        assert (
            scheduling_job.kwargs["asset_or_sensor"]["id"]
            == sensor_1.generic_asset.parent_asset.id
        ), "first queued job is the one for the top-level asset"
    assert scheduling_job.kwargs["start"] == parse_datetime(message["start"])
    assert done_job_id == job_id

    # process the scheduling queue
    work_on_rq(app.queues["scheduling"], exc_handler=handle_scheduling_exception)
    assert (
        Job.fetch(job_id, connection=app.queues["scheduling"].connection).is_finished
        is True
    )

    # Derive some expectations from the POSTed message
    resolution = sensor_1.event_resolution
    expected_length_of_schedule = parse_duration(message["duration"]) / resolution

    # check results are in the database

    # First, make sure the scheduler data source is now there
    scheduling_job.refresh()  # catch meta info that was added on this very instance
    scheduler_source = get_data_source_for_job(scheduling_job)
    assert scheduler_source is not None

    # try to retrieve the schedule for each sensor through the /sensors/<id>/schedules/<job_id> [GET] api endpoint
    for flex_model in message["flex-model"]:

        # We expect a longer schedule if the targets exceeds the original duration in the trigger
        if sequential and "soc-targets" in flex_model:
            for t in flex_model["soc-targets"]:
                duration = pd.Timestamp(t["datetime"]) - pd.Timestamp(message["start"])
                if duration > pd.Timedelta(message["duration"]):
                    expected_length_of_schedule = duration / resolution

        sensor_id = flex_model["sensor"]
        get_schedule_response = client.get(
            url_for("SensorAPI:get_schedule", id=sensor_id, uuid=scheduling_job.id),
            query_string={"duration": "PT48H"},
        )
        print("Server responded with:\n%s" % get_schedule_response.json)
        assert get_schedule_response.status_code == 200
        # assert get_schedule_response.json["type"] == "GetDeviceMessageResponse"
        assert len(get_schedule_response.json["values"]) == expected_length_of_schedule
