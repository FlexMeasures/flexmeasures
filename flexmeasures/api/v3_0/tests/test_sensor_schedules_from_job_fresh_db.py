from unittest.mock import patch

from flask import url_for
import pytest
from rq.job import Job

from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.scheduling import handle_scheduling_exception
from flexmeasures.utils.job_utils import work_on_rq


def schedule_with_dummy_scheduler(app, fresh_db, sensor: Sensor) -> str:
    """Trigger a schedule with a scheduler that needs no solver, and process the job.

    Returns the job ID.
    """
    sensor.attributes["custom-scheduler"] = {
        "module": "flexmeasures.data.tests.dummy_scheduler",
        "class": "DummyScheduler",
    }
    fresh_db.session.add(sensor)
    fresh_db.session.commit()

    # Force a new job, as identical triggers in earlier tests would otherwise return their job
    message = message_for_trigger_schedule()
    message["force-new-job-creation"] = True

    with app.test_client() as client:
        trigger_response = client.post(
            url_for("SensorAPI:trigger_schedule", id=sensor.id),
            json=message,
        )
        assert trigger_response.status_code == 202
        job_id = trigger_response.json["schedule"]

    work_on_rq(
        app.queues["scheduling"],
        exc_handler=handle_scheduling_exception,
        max_jobs=1,
    )
    return job_id


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_schedule_from_job_result_without_database_query(
    app,
    fresh_db,
    add_market_prices_fresh_db,
    add_battery_assets_fresh_db,
    battery_soc_sensor_fresh_db,
    keep_scheduling_queue_empty,
    requesting_user,
):
    """With use-job-result, the schedule is read from the job, and looks just like one read from the database."""
    sensor = add_battery_assets_fresh_db["Test battery"].sensors[0]
    job_id = schedule_with_dummy_scheduler(app, fresh_db, sensor)
    url = url_for("SensorAPI:get_schedule", id=sensor.id, uuid=job_id)

    with app.test_client() as client:
        from_database = client.get(url, query_string={"duration": "PT24H"})
        with patch.object(
            Sensor,
            "search_beliefs",
            side_effect=AssertionError("The database should not be queried"),
        ):
            from_job = client.get(
                url, query_string={"duration": "PT24H", "use-job-result": True}
            )

    assert from_database.status_code == 200
    assert from_job.status_code == 200
    assert len(from_job.json["values"]) == 96
    assert from_job.json == from_database.json


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_schedule_from_job_result_falls_back_to_the_database(
    app,
    fresh_db,
    add_market_prices_fresh_db,
    add_battery_assets_fresh_db,
    battery_soc_sensor_fresh_db,
    keep_scheduling_queue_empty,
    requesting_user,
):
    """If the job kept no values (e.g. it ran before jobs kept them), the database is used."""
    sensor = add_battery_assets_fresh_db["Test battery"].sensors[0]
    job_id = schedule_with_dummy_scheduler(app, fresh_db, sensor)

    job = Job.fetch(job_id, connection=app.queues["scheduling"].connection)
    del job.meta["schedules"]
    job.save_meta()

    url = url_for("SensorAPI:get_schedule", id=sensor.id, uuid=job_id)
    with app.test_client() as client:
        from_database = client.get(url, query_string={"duration": "PT24H"})
        from_job = client.get(
            url, query_string={"duration": "PT24H", "use-job-result": True}
        )

    assert from_job.status_code == 200
    assert from_job.json == from_database.json
