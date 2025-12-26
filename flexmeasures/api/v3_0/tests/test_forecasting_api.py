import pytest
from flask import url_for
from flexmeasures.api.tests.utils import get_auth_token


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
        "sensor": sensor.id,
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
    assert "forecast" in response_json
    assert "message" in response_json
    assert "status" in response_json

    # get the wrap-up job
    wrap_up_job = app.queues["forecasting"].fetch_job(response_json["forecast"])

    # get the forecast job IDs from the wrap-up job kwargs
    forecast_jobs = wrap_up_job.kwargs.get("cycle_job_ids", [])

    assert isinstance(forecast_jobs, list)
    assert len(forecast_jobs) >= 1
    for job_id in forecast_jobs:
        # Check the job exists in the queue or registries
        job = app.queues["forecasting"].fetch_job(job_id)
        assert job is not None, f"Job {job_id} should exist"

    # Optional: check status and message
    assert response_json["status"] == "PROCESSED"
    assert "processed" in response_json["message"].lower()
