from flask import url_for
import pytest
from isodate import parse_datetime, parse_duration

import pandas as pd
from rq.job import Job

from flexmeasures.api.common.responses import unknown_schedule, unrecognized_event
from flexmeasures.api.tests.utils import check_deprecation
from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.data.services.scheduling import (
    handle_scheduling_exception,
    get_data_source_for_job,
)
from flexmeasures.utils.calculations import integrate_time_series


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_schedule_wrong_job_id(
    app,
    add_market_prices,
    add_battery_assets,
    battery_soc_sensor,
    add_charging_station_assets,
    keep_scheduling_queue_empty,
    requesting_user,
):
    wrong_job_id = 9999
    sensor = add_battery_assets["Test battery"].sensors[0]
    with app.test_client() as client:
        get_schedule_response = client.get(
            url_for("SensorAPI:get_schedule", id=sensor.id, uuid=wrong_job_id),
        )
    print("Server responded with:\n%s" % get_schedule_response.json)
    check_deprecation(get_schedule_response, deprecation=None, sunset=None)
    assert get_schedule_response.status_code == 400
    assert get_schedule_response.json == unrecognized_event(wrong_job_id, "job")[0]


@pytest.mark.parametrize(
    "message, field, sent_value, err_msg",
    [
        (message_for_trigger_schedule(), "soc-minn", 3, "Unknown field"),
        (
            message_for_trigger_schedule(),
            "soc-min",
            "not-a-float",
            "Not a valid number",
        ),
        (message_for_trigger_schedule(), "soc-unit", "MWH", "Must be one of"),
        # todo: add back test in case we stop grandfathering ignoring too-far-into-the-future targets, or amend otherwise
        # (
        #     message_for_trigger_schedule(
        #         with_targets=True, too_far_into_the_future_targets=True
        #     ),
        #     "soc-targets",
        #     None,
        #     "Target datetime exceeds",
        # ),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_schedule_with_invalid_flexmodel(
    app,
    add_battery_assets,
    keep_scheduling_queue_empty,
    message,
    field,
    sent_value,
    err_msg,
    requesting_user,
):
    sensor = add_battery_assets["Test battery"].sensors[0]
    with app.test_client() as client:
        if sent_value:  # if None, field is a term we expect in the response, not more
            message["flex-model"][field] = sent_value

        trigger_schedule_response = client.post(
            url_for("SensorAPI:trigger_schedule", id=sensor.id),
            json=message,
        )
        print("Server responded with:\n%s" % trigger_schedule_response.json)
        check_deprecation(trigger_schedule_response, deprecation=None, sunset=None)
        assert trigger_schedule_response.status_code == 422
        assert field in trigger_schedule_response.json["message"]["json"]
        if isinstance(trigger_schedule_response.json["message"]["json"], str):
            # ValueError
            assert err_msg in trigger_schedule_response.json["message"]["json"]
        else:
            # ValidationError (marshmallow)
            assert (
                err_msg in trigger_schedule_response.json["message"]["json"][field][0]
            )


@pytest.mark.parametrize("message", [message_for_trigger_schedule(unknown_prices=True)])
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_and_get_schedule_with_unknown_prices(
    app,
    client,
    add_market_prices,
    add_battery_assets,
    battery_soc_sensor,
    add_charging_station_assets,
    keep_scheduling_queue_empty,
    message,
    requesting_user,
):
    sensor = add_battery_assets["Test battery"].sensors[0]

    # trigger a schedule through the /sensors/<id>/schedules/trigger [POST] api endpoint
    trigger_schedule_response = client.post(
        url_for("SensorAPI:trigger_schedule", id=sensor.id),
        json=message,
    )
    print("Server responded with:\n%s" % trigger_schedule_response.json)
    check_deprecation(trigger_schedule_response, deprecation=None, sunset=None)
    assert trigger_schedule_response.status_code == 200
    job_id = trigger_schedule_response.json["schedule"]

    # look for scheduling jobs in queue
    assert (
        len(app.queues["scheduling"]) == 1
    )  # only 1 schedule should be made for 1 asset
    job = app.queues["scheduling"].jobs[0]
    assert job.kwargs["asset_or_sensor"]["id"] == sensor.id
    assert job.kwargs["start"] == parse_datetime(message["start"])
    assert job.id == job_id

    # process the scheduling queue
    work_on_rq(app.queues["scheduling"], exc_handler=handle_scheduling_exception)
    assert (
        Job.fetch(job_id, connection=app.queues["scheduling"].connection).is_failed
        is True
    )

    # check results are not in the database
    scheduler_source = DataSource.query.filter_by(
        name="Seita", type="scheduler"
    ).one_or_none()
    assert (
        scheduler_source is None
    )  # Make sure the scheduler data source is still not there

    # try to retrieve the schedule through the /sensors/<id>/schedules/<job_id> [GET] api endpoint
    get_schedule_response = client.get(
        url_for("SensorAPI:get_schedule", id=sensor.id, uuid=job_id),
    )
    print("Server responded with:\n%s" % get_schedule_response.json)
    check_deprecation(get_schedule_response, deprecation=None, sunset=None)
    assert get_schedule_response.status_code == 400
    assert get_schedule_response.json["status"] == unknown_schedule()[0]["status"]
    assert "prices unknown" in get_schedule_response.json["message"].lower()


@pytest.mark.parametrize(
    "message, asset_name",
    [
        (message_for_trigger_schedule(), "Test battery"),
        (message_for_trigger_schedule(with_targets=True), "Test charging station"),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_and_get_schedule(
    app,
    add_market_prices,
    add_battery_assets,
    battery_soc_sensor,
    add_charging_station_assets,
    keep_scheduling_queue_empty,
    message,
    asset_name,
    requesting_user,
):  # noqa: C901
    # Include the price sensor and site-power-capacity in the flex-context explicitly, to test deserialization
    price_sensor_id = add_market_prices["epex_da"].id
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
            [parse_datetime(soc_target["datetime"]) for soc_target in soc_targets]
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
            assert soc_schedule[target["datetime"]] == target["value"] / 1000

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


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_schedule_fallback(
    app,
    add_battery_assets,
    add_market_prices,
    battery_soc_sensor,
    add_charging_station_assets,
    keep_scheduling_queue_empty,
    requesting_user,
):
    """
    Test if the fallback job is created after a failing StorageScheduler call. This test
    is based on flexmeasures/data/models/planning/tests/test_solver.py
    """
    assert app.config["FLEXMEASURES_FALLBACK_REDIRECT"] is False
    app.config["FLEXMEASURES_FALLBACK_REDIRECT"] = True

    target_soc = 9
    charging_station_name = "Test charging station"

    start = "2015-01-02T00:00:00+01:00"
    epex_da = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    charging_station = add_charging_station_assets[charging_station_name].sensors[0]

    assert charging_station.get_attribute("capacity_in_mw") == 2
    assert charging_station.get_attribute("market_id") == epex_da.id

    # check that no Fallback schedule has been saved before
    models = [
        source.model for source in charging_station.search_beliefs().sources.unique()
    ]
    assert "StorageFallbackScheduler" not in models

    # create a scenario that yields an infeasible problem (unreachable target SOC at 2am)
    message = {
        "start": start,
        "duration": "PT24H",
        "flex-model": {
            "soc-at-start": 10,
            "soc-min": charging_station.get_attribute("min_soc_in_mwh", 0),
            "soc-max": charging_station.get_attribute("max-soc-in-mwh", target_soc),
            "roundtrip-efficiency": charging_station.get_attribute(
                "roundtrip-efficiency", 1
            ),
            "storage-efficiency": charging_station.get_attribute(
                "storage-efficiency", 1
            ),
            "soc-targets": [
                {"value": target_soc, "datetime": "2015-01-02T02:00:00+01:00"}
            ],
        },
    }

    with app.test_client() as client:
        # trigger storage scheduler
        trigger_schedule_response = client.post(
            url_for("SensorAPI:trigger_schedule", id=charging_station.id),
            json=message,
        )

        # check that the call is successful
        assert trigger_schedule_response.status_code == 200
        job_id = trigger_schedule_response.json["schedule"]

        # look for scheduling jobs in queue
        assert (
            len(app.queues["scheduling"]) == 1
        )  # only 1 schedule should be made for 1 asset
        job = app.queues["scheduling"].jobs[0]
        assert job.kwargs["asset_or_sensor"]["id"] == charging_station.id
        assert job.kwargs["start"] == parse_datetime(message["start"])
        assert job.id == job_id

        # process only the job that runs the storage scheduler (max_jobs=1)
        work_on_rq(
            app.queues["scheduling"],
            exc_handler=handle_scheduling_exception,
            max_jobs=1,
        )

        # check that the job is failing
        assert Job.fetch(
            job_id, connection=app.queues["scheduling"].connection
        ).is_failed

        # the callback creates the fallback job which is still pending
        assert len(app.queues["scheduling"]) == 1
        fallback_job_id = Job.fetch(
            job_id, connection=app.queues["scheduling"].connection
        ).meta.get("fallback_job_id")

        # check that the fallback_job_id is stored on the metadata of the original job
        assert app.queues["scheduling"].get_job_ids()[0] == fallback_job_id
        assert fallback_job_id != job_id

        get_schedule_response = client.get(
            url_for("SensorAPI:get_schedule", id=charging_station.id, uuid=job_id),
        )
        # requesting the original job redirects to the fallback job
        assert (
            get_schedule_response.status_code == 303
        )  # Status code for redirect ("See other")
        assert (
            get_schedule_response.json["message"]
            == "Scheduling job failed with InfeasibleProblemException: . StorageScheduler was used."
        )
        assert get_schedule_response.json["status"] == "UNKNOWN_SCHEDULE"
        assert get_schedule_response.json["result"] == "Rejected"

        # check that the redirection location points to the fallback job
        assert (
            get_schedule_response.headers["location"]
            == f"http://localhost/api/v3_0/sensors/{charging_station.id}/schedules/{fallback_job_id}"
        )

        # run the fallback job
        work_on_rq(
            app.queues["scheduling"],
            exc_handler=handle_scheduling_exception,
            max_jobs=1,
        )

        # check that the queue is empty
        assert len(app.queues["scheduling"]) == 0

        # get the fallback schedule
        fallback_schedule = client.get(
            get_schedule_response.headers["location"],
            json={"duration": "PT24H"},
        ).json

        # check that the fallback schedule has the right status and start dates
        assert fallback_schedule["status"] == "PROCESSED"
        assert parse_datetime(fallback_schedule["start"]) == parse_datetime(start)

        models = [
            source.model
            for source in charging_station.search_beliefs().sources.unique()
        ]
        assert "StorageFallbackScheduler" in models

        app.config["FLEXMEASURES_FALLBACK_REDIRECT"] = False


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_schedule_fallback_not_redirect(
    app,
    add_battery_assets,
    add_market_prices,
    battery_soc_sensor,
    add_charging_station_assets,
    keep_scheduling_queue_empty,
    requesting_user,
):
    """
    Test if the fallback scheduler is returned directly after a failing StorageScheduler call. This test
    is based on flexmeasures/data/models/planning/tests/test_solver.py
    """
    app.config["FLEXMEASURES_FALLBACK_REDIRECT"] = False

    target_soc = 9
    charging_station_name = "Test charging station"

    start = "2015-01-02T00:00:00+01:00"
    epex_da = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    charging_station = add_charging_station_assets[charging_station_name].sensors[0]

    assert charging_station.get_attribute("capacity_in_mw") == 2
    assert charging_station.get_attribute("market_id") == epex_da.id

    # create a scenario that yields an infeasible problem (unreachable target SOC at 2am)
    message = {
        "start": start,
        "duration": "PT24H",
        "flex-model": {
            "soc-at-start": 10,
            "soc-min": charging_station.get_attribute("min_soc_in_mwh", 0),
            "soc-max": charging_station.get_attribute("max-soc-in-mwh", target_soc),
            "roundtrip-efficiency": charging_station.get_attribute(
                "roundtrip-efficiency", 1
            ),
            "storage-efficiency": charging_station.get_attribute(
                "storage-efficiency", 1
            ),
            "soc-targets": [
                {"value": target_soc, "datetime": "2015-01-02T02:00:00+01:00"}
            ],
        },
    }

    with app.test_client() as client:
        # trigger storage scheduler
        trigger_schedule_response = client.post(
            url_for("SensorAPI:trigger_schedule", id=charging_station.id),
            json=message,
        )

        # check that the call is successful
        assert trigger_schedule_response.status_code == 200
        job_id = trigger_schedule_response.json["schedule"]

        # look for scheduling jobs in queue
        assert (
            len(app.queues["scheduling"]) == 1
        )  # only 1 schedule should be made for 1 asset
        job = app.queues["scheduling"].jobs[0]
        assert job.kwargs["asset_or_sensor"]["id"] == charging_station.id
        assert job.kwargs["start"] == parse_datetime(message["start"])
        assert job.id == job_id

        # process only the job that runs the storage scheduler (max_jobs=1)
        work_on_rq(
            app.queues["scheduling"],
            exc_handler=handle_scheduling_exception,
            max_jobs=1,
        )

        # check that the job is failing
        assert Job.fetch(
            job_id, connection=app.queues["scheduling"].connection
        ).is_failed

        # the callback creates the fallback job which is still pending
        assert len(app.queues["scheduling"]) == 1

        fallback_job_id = Job.fetch(
            job_id, connection=app.queues["scheduling"].connection
        ).meta.get("fallback_job_id")

        # check that the fallback_job_id is stored on the metadata of the original job
        assert app.queues["scheduling"].get_job_ids()[0] == fallback_job_id
        assert fallback_job_id != job_id

        get_schedule_response = client.get(
            url_for("SensorAPI:get_schedule", id=charging_station.id, uuid=job_id),
        )

        work_on_rq(
            app.queues["scheduling"],
            exc_handler=handle_scheduling_exception,
            max_jobs=1,
        )

        get_schedule_response = client.get(
            url_for("SensorAPI:get_schedule", id=charging_station.id, uuid=job_id),
        )

        assert get_schedule_response.status_code == 200

        schedule = get_schedule_response.json

        # check that the fallback schedule has the right status and start dates
        assert schedule["status"] == "PROCESSED"
        assert parse_datetime(schedule["start"]) == parse_datetime(start)
        assert schedule["scheduler_info"]["scheduler"] == "StorageFallbackScheduler"

        app.config["FLEXMEASURES_FALLBACK_REDIRECT"] = False
