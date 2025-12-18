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
    1. Trigger forecasting 2 jobs for 2 forecasting cycles via /<sensor>/forecasts
    2. Execute forecasting queue synchronously
    3. Fetch each job's results via /<sensor>/forecasts/<job_id>
    4. Compare returned forecasts computed directly from the DB with those returned by the API
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
        "max_forecast_horizon": "PT1H",
        "retrain_frequency": "PT1H",
    }

    trigger_url = url_for("SensorAPI:trigger_forecast", id=sensor_0.id)
    trigger_res = client.post(
        trigger_url, json=payload, headers={"Authorization": token}
    )
    assert trigger_res.status_code == 200

    trigger_json = trigger_res.get_json()
    wrap_up_job = app.queues["forecasting"].fetch_job(trigger_json["forecast"])
    job_ids = wrap_up_job.kwargs.get("cycle_job_ids", [])

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

        # Load only the latest belief per event_start
        forecasts_df = sensor_1.search_beliefs(
            event_starts_after=job.kwargs.get("predict_start"),
            event_ends_before=job.kwargs.get("predict_end") + sensor_1.event_resolution,
            source=data_source,
            most_recent_beliefs_only=True,
            use_latest_version_per_event=True,
        ).reset_index()

        # Transform computed forecasts into the expected API format
        latest_forecasts = defaultdict(list)
        for row in forecasts_df.itertuples():
            event_key = row.event_start.isoformat()
            latest_forecasts[event_key].append(
                {
                    "event_start": row.event_start.isoformat(),
                    "belief_time": row.belief_time.isoformat(),
                    "cumulative_probability": row.cumulative_probability,
                    "value": row.event_value,
                }
            )

        # API should return exactly these most-recent beliefs
        assert api_forecasts == latest_forecasts
