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
