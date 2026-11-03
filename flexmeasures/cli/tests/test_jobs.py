from __future__ import annotations

import os
from typing import Callable

import pytest
from rq import SimpleWorker
from sqlalchemy import text

from flexmeasures.data import db


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


def test_check_source_references(app, db, clean_job_redis, monkeypatch):
    """Waiting jobs referring to a data source that does not exist, or that a database upgrade will merge, are listed; other jobs are not."""
    from datetime import timedelta

    from flexmeasures.cli import jobs as jobs_cli
    from flexmeasures.data.services.data_sources import get_or_create_source

    runner = app.test_cli_runner()

    with app.app_context():
        existing_id = get_or_create_source(
            "test-referenced-source", source_type="scheduler"
        ).id
        db.session.commit()
        missing_id = existing_id + 1000

        def flex_context(source_ids: list[int]) -> dict:
            return {"consumption-price": {"sensor": 1, "sources": source_ids}}

        queue = app.queues["scheduling"]
        job_missing = queue.enqueue(print, flex_context=flex_context([missing_id]))
        job_existing = queue.enqueue_in(
            timedelta(hours=1), print, flex_context=flex_context([existing_id])
        )
        job_without_sources = queue.enqueue(print, flex_context={})

    result = runner.invoke(jobs_cli.fm_jobs, ["check-source-references"])
    assert result.exit_code == 0, result.output
    assert job_missing.id in result.output
    assert "does not exist" in result.output
    assert job_existing.id not in result.output
    assert job_without_sources.id not in result.output

    # Before a database upgrade merges duplicates, a reference to a duplicate is listed, too.
    monkeypatch.setattr(jobs_cli, "find_duplicate_sources", lambda: {existing_id: 1})
    result = runner.invoke(jobs_cli.fm_jobs, ["check-source-references"])
    assert result.exit_code == 0, result.output
    assert job_existing.id in result.output
    assert "will be merged into data source 1" in result.output
    assert job_without_sources.id not in result.output


def test_check_source_references_reports_reporting_jobs(
    app, db, clean_job_redis, monkeypatch
):
    """Report jobs pass their source ID directly, and fail if that source is merged or missing."""
    from flexmeasures.cli import jobs as jobs_cli
    from flexmeasures.data.services.data_sources import get_or_create_source
    from flexmeasures.data.services.reporting import run_report_job

    runner = app.test_cli_runner()
    with app.app_context():
        source_id = get_or_create_source(
            "test-report-job-source", source_type="reporter"
        ).id
        db.session.commit()
        missing_id = source_id + 1000
        queue = app.queues["reporting"]
        missing_job = queue.enqueue(
            run_report_job, data_source_id=missing_id, parameters={}
        )
        merging_job = queue.enqueue(
            run_report_job, data_source_id=source_id, parameters={}
        )

    monkeypatch.setattr(jobs_cli, "find_duplicate_sources", lambda: {source_id: 1})
    result = runner.invoke(jobs_cli.fm_jobs, ["check-source-references"])
    assert result.exit_code == 0, result.output
    assert missing_job.id in result.output
    assert "does not exist" in result.output
    assert merging_job.id in result.output
    assert "will be merged into data source 1" in result.output


def run_in_forked_process(work: Callable[[], str]) -> str:
    """Run work in a forked process, as RQ's Worker does with each job, and return what it reports.

    The forked process reports an exception as its type and message, so the test can show it.
    """
    read_end, write_end = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(read_end)
            try:
                outcome = work()
            except Exception as exc:
                outcome = f"{type(exc).__name__}: {exc}"
            os.write(write_end, outcome.encode())
        finally:
            # Leave without cleaning up, like a job's process, and without running pytest's teardown here.
            os._exit(0)
    os.close(write_end)
    os.waitpid(pid, 0)
    with os.fdopen(read_end) as reader:
        return reader.read()


def query_backend_and_leave_transaction_open() -> str:
    """Return the ID of the Postgres session serving this process, leaving the transaction this query began open."""
    return str(db.session.execute(text("SELECT pg_backend_pid()")).scalar())


def assert_jobs_used_their_own_sessions(first_job: str, second_job: str):
    """Each job should have reported the ID of its own Postgres session, rather than an error."""
    assert first_job.isdigit(), first_job
    assert second_job.isdigit(), second_job
    assert first_job != second_job, "Both jobs used the same Postgres session."


def test_forked_jobs_do_not_inherit_the_workers_session(app):
    """A job should not continue the worker's session, nor a transaction an earlier job left open (#2806).

    At startup, the worker uses the database, and its session can keep the connection it used.
    """
    from flexmeasures.cli.jobs import release_database_connections_before_forking

    with app.app_context():
        db.session.execute(text("SELECT 1"))
        release_database_connections_before_forking()
        first_job = run_in_forked_process(query_backend_and_leave_transaction_open)
        second_job = run_in_forked_process(query_backend_and_leave_transaction_open)

    assert_jobs_used_their_own_sessions(first_job, second_job)


def test_forked_jobs_do_not_inherit_connections_the_worker_opens_later(app):
    """A job should not use a connection the worker pooled after it started (#2806)."""
    from flexmeasures.cli.jobs import release_database_connections_before_forking

    with app.app_context():
        release_database_connections_before_forking()
        db.session.execute(text("SELECT 1"))
        db.session.commit()
        first_job = run_in_forked_process(query_backend_and_leave_transaction_open)
        second_job = run_in_forked_process(query_backend_and_leave_transaction_open)

    assert_jobs_used_their_own_sessions(first_job, second_job)
