from datetime import datetime

from rq.job import Job
from sqlalchemy import select

from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.services.forecasting import handle_forecasting_exception
from flexmeasures.data.tests.test_forecasting_jobs import queue_forecasting_job
from flexmeasures.utils.job_utils import work_on_rq


def test_forecasting_job_runs_on_fresh_db(
    app,
    clean_redis,
    fresh_db,
    setup_fresh_test_forecast_data,
):
    sensor = setup_fresh_test_forecast_data["solar-sensor"]

    pipeline_returns = queue_forecasting_job(
        sensor.id,
        start=datetime(2025, 1, 5, 0),
        end=datetime(2025, 1, 5, 2),
    )

    job = app.queues["forecasting"].fetch_job(pipeline_returns["job_id"])
    assert job is not None

    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)

    refreshed_job = Job.fetch(job.id, connection=app.queues["forecasting"].connection)
    assert refreshed_job.is_finished

    forecasts = fresh_db.session.scalars(
        select(TimedBelief).filter(TimedBelief.sensor_id == sensor.id)
    ).all()
    assert forecasts
