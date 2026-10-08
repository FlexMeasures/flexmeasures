import json
from datetime import datetime, timezone

import pytest

from flask import current_app
from rq.job import Job


def _rq_test_function(**kwargs):
    return kwargs


def _fail_with_a_refusal():
    from flexmeasures.data.services.generator_results import (
        GeneratorWritesUncheckedSensor,
    )

    raise GeneratorWritesUncheckedSensor(
        "StorageScheduler", [12], [1, 3], automation_id=7
    )


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


@pytest.mark.parametrize(
    "queue_name, func, args, expected_summary",
    [
        (
            queue_name,
            "math.sqrt",
            (-1,),
            {"type": "ValueError", "message": "math domain error"},
        )
        for queue_name in ("scheduling", "forecasting", "reporting", "ingestion")
    ]
    + [
        (
            "scheduling",
            _fail_with_a_refusal,
            (),
            {
                "type": "GeneratorWritesUncheckedSensor",
                "generator": "StorageScheduler",
                "refused_sensor_ids": [12],
                "permitted_sensor_ids": [1, 3],
                "automation_id": 7,
            },
        )
    ],
)
def test_a_failed_job_shows_on_the_dashboard(
    client, app, clean_redis, as_admin, queue_name, func, args, expected_summary
):
    """A job failed through its queue's own exception handler can be opened on the dashboard, which shows why it failed."""
    from flexmeasures.cli.jobs import get_exception_handler
    from flexmeasures.utils.job_utils import work_on_rq

    _make_rq_dashboard_use_test_redis(app)
    queue = app.queues[queue_name]
    try:
        job = queue.enqueue(func, *args)
        work_on_rq(queue, exc_handler=get_exception_handler(queue_name), job=job)

        page = client.get(f"/tasks/0/view/job/{job.id}", follow_redirects=True)
        assert page.status_code == 200

        details = client.get(f"/tasks/0/data/job/{job.id}.json", follow_redirects=True)
        assert details.status_code == 200
        assert details.json["status"] == "failed"
        assert expected_summary["type"] in details.json["exc_info"]
        stored = json.loads(details.json["metadata"])["exception"]
        assert expected_summary.items() <= stored.items()

        failed = client.get(
            f"/tasks/0/data/jobs/{queue_name}/failed/10/asc/1.json",
            follow_redirects=True,
        )
        assert failed.status_code == 200
        assert job.id in [listed["id"] for listed in failed.json["jobs"]]
    finally:
        # Leave no failed job behind, which clean_redis cannot fetch again on the next run.
        app.redis_connection.flushdb()
