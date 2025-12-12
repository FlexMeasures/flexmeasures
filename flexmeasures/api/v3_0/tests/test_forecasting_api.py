from flask import current_app
import pytest
from flask import url_for
from flexmeasures.data.services.scheduling import (
    get_data_source_for_job,
)
from rq.job import Job
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.data.services.forecasting import handle_forecasting_exception
from flexmeasures.data.models.forecasting.pipelines import TrainPredictPipeline
from collections import defaultdict


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_trigger_forecast_endpoint(
    app,
    setup_fresh_test_forecast_data,
    setup_roles_users_fresh_db,
    requesting_user,
):
    """
    Test that triggering forecasts enqueues RQ jobs and returns their job IDs.
    """

    client = app.test_client()
    token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    sensor = setup_fresh_test_forecast_data["solar-sensor"]
    payload = {
        "start_date": "2025-01-01T00:00:00+00:00",
        "start_predict_date": "2025-01-05T00:00:00+00:00",
        "end_date": "2025-01-07T23:00:00+00:00",
    }

    url = url_for("SensorAPI:trigger_forecast", id=sensor.id)

    response = client.post(
        url,
        json=payload,
        headers={"Authorization": token},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None

    # Check that the response contains job IDs
    response_json = response.get_json()

    # Top-level keys
    assert "forecasting_jobs" in response_json
    assert "message" in response_json
    assert "status" in response_json

    # forecast_jobs should be a non-empty list of strings (UUIDs)
    forecast_jobs = response_json["forecasting_jobs"]
    assert isinstance(forecast_jobs, list)
    assert len(forecast_jobs) >= 1
    for job_id in forecast_jobs:
        # Check the job exists in the queue or registries
        job = app.queues["forecasting"].fetch_job(job_id)
        assert job is not None, f"Job {job_id} should exist"

    # Optional: check status and message
    assert response_json["status"] == "PROCESSED"
    assert "processed" in response_json["message"].lower()


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_trigger_and_fetch_forecasts(
    app,
    setup_fresh_test_forecast_data,
    setup_roles_users_fresh_db,
    requesting_user,
):
    """
    Full test:
    1. Trigger forecasting job(s)
    2. Execute forecasting queue synchronously
    3. Fetch each job's results via /<sensor>/forecasts/<job_id>
    4. Validate returned forecasts compared to forecasts ran directly via pipeline
    """

    client = app.test_client()
    token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    sensor = setup_fresh_test_forecast_data["solar-sensor"]

    # Trigger job
    payload = {
        "start_date": "2025-01-01T00:00:00+00:00",
        "start_predict_date": "2025-01-05T00:00:00+00:00",
        "end_date": "2025-01-05T04:00:00+00:00",
    }

    trigger_url = url_for("SensorAPI:trigger_forecast", id=sensor.id)
    trigger_res = client.post(
        trigger_url, json=payload, headers={"Authorization": token}
    )
    assert trigger_res.status_code == 200

    trigger_json = trigger_res.get_json()
    job_ids = trigger_json["forecasting_jobs"]
    assert len(job_ids) >= 1

    # Run forecasting queue
    work_on_rq(
        app.queues["forecasting"],
        exc_handler=handle_forecasting_exception,
    )

    # Fetch forecasts for each job
    for job_id in job_ids:
        fetch_url = url_for(
            "SensorAPI:check_forecasts", id=sensor.id, uuid=job_id
        )
        res = client.get(fetch_url, headers={"Authorization": token})
        assert res.status_code == 200

        data = res.get_json()

        # Validate structure
        assert data["status"] == "FINISHED"
        assert data["job_id"] == job_id
        assert data["sensor"] == sensor.id
        assert "forecasts" in data

        forecasts_1 = data["forecasts"]

        # forecasts is a dict keyed by event_start timestamps
        assert isinstance(forecasts_1, dict)
        assert len(forecasts_1) > 0

        sensor = setup_fresh_test_forecast_data["solar-sensor-1"]
        payload["sensor"] = sensor.id
        pipeline = TrainPredictPipeline()
        pipeline.compute(parameters=payload)

        # Fetch forecasting job from queue
        queue = current_app.queues["forecasting"]
        job = Job.fetch(job_id, connection=queue.connection)

        # Fetch data source used in job
        data_source = get_data_source_for_job(job, type="forecasting")

        forecasts = sensor.search_beliefs(
            event_starts_after="2025-01-05T00:00:00+00:00",
            event_ends_before="2025-01-05T04:00:00+00:00",
            source=data_source,
            most_recent_beliefs_only=True,
            use_latest_version_per_event=True,
        ).reset_index()

        forecast_2 = defaultdict(list)

        for row in forecasts.itertuples():
            event_key = row.event_start.isoformat()

            forecast_2[event_key].append(
                {
                    "event_start": row.event_start.isoformat(),
                    "belief_time": row.belief_time.isoformat(),
                    "cumulative_probability": row.cumulative_probability,
                    "value": row.event_value,
                }
            )

        assert forecasts_1 == forecast_2
