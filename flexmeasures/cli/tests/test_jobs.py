from __future__ import annotations

import pytest
from rq import SimpleWorker


@pytest.fixture
def clean_job_redis(app):
    app.redis_connection.flushdb()
    yield
    app.redis_connection.flushdb()


def test_inspect_job_returns_job_status_table(app, clean_job_redis):
    from flexmeasures.cli.jobs import fm_jobs

    runner = app.test_cli_runner()

    with app.app_context():
        job = app.queues["scheduling"].enqueue(sum, [1, 2])

    result = runner.invoke(fm_jobs, ["inspect-job", "--job", job.id])
    assert result.exit_code == 0, result.output

    # Check that tabular output contains the expected job information
    output = result.output
    assert (
        "Field" in output and "Value" in output
    ), f"Expected table header with 'Field' and 'Value', got: {output}"
    assert "Status       QUEUED" in output
    assert "Scheduling job waiting to be processed." in output
    assert "builtins.sum" in output, f"Expected function name in output, got: {output}"
    assert "scheduling" in output, f"Expected queue name in output, got: {output}"
    assert "Message" in output, f"Expected 'Message' field in output, got: {output}"


def test_inspect_failed_job_uses_rq_result_exception_info(app, clean_job_redis):
    from flexmeasures.cli.jobs import fm_jobs

    runner = app.test_cli_runner()

    with app.app_context():
        queue = app.queues["scheduling"]
        job = queue.enqueue("math.sqrt", -1)
        worker = SimpleWorker([queue], connection=queue.connection)
        worker.perform_job(job, queue)

        # Simulate a plain RQ failure without FlexMeasures' exception handler metadata.
        job.meta.pop("exception", None)
        job.save_meta()

    result = runner.invoke(fm_jobs, ["inspect-job", "--job", job.id])
    assert result.exit_code == 0, result.output

    output = result.output
    assert "Status       FAILED" in output
    assert "Scheduling job failed with ValueError: math domain error." in output
    assert "Exception Info:" in output
    assert "ValueError: math domain error" in output
    assert "does not state why it failed" not in output


def test_inspect_job_error_when_job_not_found(app):
    from flexmeasures.cli.jobs import fm_jobs

    runner = app.test_cli_runner()
    result = runner.invoke(
        fm_jobs,
        ["inspect-job", "--job", "00000000-0000-0000-0000-000000000000"],
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


CALLS: list[str] = []


def record_call() -> int:
    """Record that this function ran, and return how often it ran so far.

    Used to count how often a job's function is performed.
    """
    CALLS.append("called")
    return len(CALLS)


@pytest.fixture
def clean_call_record():
    CALLS.clear()
    yield
    CALLS.clear()


def test_run_job_performs_the_job_exactly_once(app, clean_job_redis, clean_call_record):
    """The job's function should run once, and its result should be reported."""
    from flexmeasures.cli.jobs import fm_jobs

    runner = app.test_cli_runner()

    with app.app_context():
        job = app.queues["scheduling"].enqueue(record_call)

    result = runner.invoke(fm_jobs, ["run-job", "--job", job.id])
    assert result.exit_code == 0, result.output

    assert CALLS == ["called"], f"Job function ran {len(CALLS)} time(s)."
    assert f"Job {job.id} finished with: 1" in result.output


def test_run_job_uses_the_queue_the_job_belongs_to(app, clean_job_redis):
    """A failing forecasting job should be handled by the forecasting queue's exception handler.

    That handler stores a dict in the job's meta, whereas the generic fallback handler stores a plain string.
    """
    from flexmeasures.cli.jobs import fm_jobs
    from rq.job import Job

    runner = app.test_cli_runner()

    with app.app_context():
        job = app.queues["forecasting"].enqueue("math.sqrt", -1)

    result = runner.invoke(fm_jobs, ["run-job", "--job", job.id])
    assert result.exit_code == 0, result.output

    with app.app_context():
        job = Job.fetch(job.id, connection=app.redis_connection)
        assert job.is_failed
        exception = job.meta["exception"]
        assert isinstance(
            exception, dict
        ), f"Expected the forecasting queue's exception handler to store a dict, got: {exception!r}"
        assert exception["type"] == "ValueError"
        assert job.id in app.queues["forecasting"].failed_job_registry.get_job_ids()


def test_run_job_errors_on_a_queue_flexmeasures_does_not_have(app, clean_job_redis):
    """A job on an unknown queue should lead to a clear CLI error, rather than a traceback."""
    from flexmeasures.cli.jobs import fm_jobs
    from rq import Queue

    runner = app.test_cli_runner()

    with app.app_context():
        job = Queue("some-other-queue", connection=app.redis_connection).enqueue(
            sum, [1, 2]
        )

    result = runner.invoke(fm_jobs, ["run-job", "--job", job.id])
    assert result.exit_code != 0
    assert "Unknown queue 'some-other-queue'." in result.output


def test_run_job_errors_on_a_missing_job(app, clean_job_redis):
    from flexmeasures.cli.jobs import fm_jobs

    runner = app.test_cli_runner()
    result = runner.invoke(
        fm_jobs, ["run-job", "--job", "00000000-0000-0000-0000-000000000000"]
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower()
