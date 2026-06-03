from datetime import datetime, timezone

from flask import current_app
from rq.job import Job


def _rq_test_function(**kwargs):
    return kwargs


def _make_rq_dashboard_use_test_redis(app):
    """Ensure rq-dashboard requests use the same Redis connection as app queues."""

    def _use_test_redis_connection():
        current_app.redis_conn = app.redis_connection

    app.before_request_funcs["rq_dashboard"].append(_use_test_redis_connection)


def _enqueue_job_with_non_json_fields(
    app, *, kwargs_value=None, metadata_value=None
) -> Job:
    job = Job.create(
        _rq_test_function,
        kwargs={"value": kwargs_value} if kwargs_value is not None else {},
        connection=app.queues["forecasting"].connection,
    )
    app.queues["forecasting"].enqueue_job(job)

    if metadata_value is not None:
        job.meta["value"] = metadata_value
        job.save_meta()

    return job


def test_job_detail_page_loads_with_non_json_metadata(
    client, app, clean_redis, as_admin
):
    """The task detail page should load when metadata contains a non-JSON value."""
    _make_rq_dashboard_use_test_redis(app)
    non_json_value = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    job = _enqueue_job_with_non_json_fields(app, metadata_value=non_json_value)

    response = client.get(f"/tasks/0/data/job/{job.id}.json", follow_redirects=True)

    assert response.status_code == 200
    assert response.json["id"] == job.id
    assert non_json_value.isoformat() in response.get_data(as_text=True)


def test_jobs_list_page_loads_with_non_json_kwargs(client, app, clean_redis, as_admin):
    """The task list page should load when kwargs contain a non-JSON value."""
    _make_rq_dashboard_use_test_redis(app)
    non_json_value = datetime(2025, 1, 1, 13, 0, tzinfo=timezone.utc)
    job = _enqueue_job_with_non_json_fields(app, kwargs_value=non_json_value)

    response = client.get(
        "/tasks/0/data/jobs/forecasting/queued/10/asc/1.json", follow_redirects=True
    )

    assert response.status_code == 200
    assert [job_data["id"] for job_data in response.json["jobs"]] == [job.id]
    assert repr(non_json_value) in response.json["jobs"][0]["description"]
