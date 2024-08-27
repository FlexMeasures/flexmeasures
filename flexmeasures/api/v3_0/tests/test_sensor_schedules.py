from flask import url_for
import pytest
from isodate import parse_datetime

from rq.job import Job
from sqlalchemy import select

from flexmeasures.api.common.responses import unknown_schedule, unrecognized_event
from flexmeasures.api.tests.utils import check_deprecation
from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.data.services.scheduling import handle_scheduling_exception
from flexmeasures.tests.utils import get_test_sensor


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
            "Cannot convert value 'not-a-float' to a valid quantity.",
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
    db,
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
    scheduler_source = db.session.execute(
        select(DataSource).filter_by(name="Seita", type="scheduler")
    ).scalar_one_or_none()
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
    db,
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
    epex_da = get_test_sensor(db)
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
    db,
):
    """
    Test if the fallback scheduler is returned directly after a failing StorageScheduler call. This test
    is based on flexmeasures/data/models/planning/tests/test_solver.py
    """
    app.config["FLEXMEASURES_FALLBACK_REDIRECT"] = False

    target_soc = 9
    charging_station_name = "Test charging station"

    start = "2015-01-02T00:00:00+01:00"
    epex_da = get_test_sensor(db)
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
