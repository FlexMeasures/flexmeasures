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

    # This sensor is used to *trigger* the forecasting jobs via the API
    sensor_0 = setup_fresh_test_forecast_data["solar-sensor"]

    # Trigger job
    payload = {
        "start_date": "2025-01-01T00:00:00+00:00",
        "start_predict_date": "2025-01-05T00:00:00+00:00",
        "end_date": "2025-01-05T02:00:00+00:00",
        "max_forecast_horizon": "PT2H",
        "retrain_frequency": "PT1H",
    }

    trigger_url = url_for("SensorAPI:trigger_forecast", id=sensor_0.id)
    trigger_res = client.post(
        trigger_url, json=payload, headers={"Authorization": token}
    )
    assert trigger_res.status_code == 200

    trigger_json = trigger_res.get_json()
    job_ids = trigger_json["forecasting_jobs"]

    # Two forecast cycles expected from payload
    assert len(job_ids) == 2

    # Ensure jobs were successfully queued
    for job_id in job_ids:
        job = app.queues["forecasting"].fetch_job(job_id)
        assert job is not None, f"Job {job_id} should exist in the queue"

    # Run forecasting queue
    work_on_rq(
        app.queues["forecasting"],
        exc_handler=handle_forecasting_exception,
    )

    # This sensor is where the directly computed forecasts will be saved
    sensor_1 = setup_fresh_test_forecast_data["solar-sensor-1"]
    payload["sensor"] = sensor_1.id

    # Run pipeline manually to compute expected forecasts
    pipeline = TrainPredictPipeline()
    pipeline.compute(parameters=payload)

    # Fetch forecasts for each job
    for job_id in job_ids:

        fetch_url = url_for("SensorAPI:check_forecasts", id=sensor_0.id, uuid=job_id)
        res = client.get(fetch_url, headers={"Authorization": token})
        assert res.status_code == 200

        data = res.get_json()

        # Validate structure
        assert data["status"] == "FINISHED"
        assert data["job_id"] == job_id
        assert data["sensor"] == sensor_0.id
        assert "forecasts" in data

        api_forecasts = data["forecasts"]
        assert isinstance(api_forecasts, dict)
        assert len(api_forecasts) > 0

        # Retrieve the job so we know which timestamps to query
        queue = current_app.queues["forecasting"]
        job = Job.fetch(job_id, connection=queue.connection)

        # Identify which data source wrote these beliefs
        data_source = get_data_source_for_job(job, type="forecasting")

        forecasts = sensor.search_beliefs(
            event_starts_after="2025-01-05T00:00:00+00:00",
            event_ends_before="2025-01-05T02:00:00+00:00",
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
