from __future__ import annotations

import json


def test_inspect_job_returns_job_status_json(app):
    from flexmeasures.cli.jobs import fm_jobs

    runner = app.test_cli_runner()

    with app.app_context():
        job = app.queues["scheduling"].enqueue(sum, [1, 2])

    result = runner.invoke(fm_jobs, ["inspect-job", "--job", job.id])
    assert result.exit_code == 0, result.output

    info = json.loads(result.output)
    assert info["status"] in {
        "QUEUED",
        "STARTED",
        "FINISHED",
        "FAILED",
        "DEFERRED",
        "SCHEDULED",
        "STOPPED",
        "CANCELED",
    }
    assert info["func_name"] == "builtins.sum"
    assert info["origin"] == "scheduling"
    assert "message" in info
    assert info["result"] is None
    assert info["enqueued_at"] is not None
    assert info["started_at"] is None
    assert info["ended_at"] is None
    assert info["exc_info"] is None


def test_inspect_job_error_when_job_not_found(app):
    from flexmeasures.cli.jobs import fm_jobs

    runner = app.test_cli_runner()
    result = runner.invoke(
        fm_jobs,
        ["inspect-job", "--job", "00000000-0000-0000-0000-000000000000"],
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower()
