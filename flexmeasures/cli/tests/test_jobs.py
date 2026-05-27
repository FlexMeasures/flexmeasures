from __future__ import annotations


def test_inspect_job_returns_job_status_table(app):
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
    assert any(
        status in output for status in ["QUEUED", "STARTED", "FINISHED", "FAILED"]
    ), f"Expected job status in output, got: {output}"
    assert "builtins.sum" in output, f"Expected function name in output, got: {output}"
    assert "scheduling" in output, f"Expected queue name in output, got: {output}"
    assert "Message" in output, f"Expected 'Message' field in output, got: {output}"


def test_inspect_job_error_when_job_not_found(app):
    from flexmeasures.cli.jobs import fm_jobs

    runner = app.test_cli_runner()
    result = runner.invoke(
        fm_jobs,
        ["inspect-job", "--job", "00000000-0000-0000-0000-000000000000"],
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower()
