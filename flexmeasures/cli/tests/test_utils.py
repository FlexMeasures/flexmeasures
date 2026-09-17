import logging
import sys
import pytest
import click

from datetime import datetime
from pytz import utc

from flexmeasures.cli import is_running as cli_is_running
from flexmeasures.cli.utils import (
    DeprecatedOption,
    DeprecatedOptionsCommand,
    LoggedClickExceptionGroup,
)
from click.testing import CliRunner


def test_cli_is_running(app, monkeypatch):
    assert cli_is_running() is False
    monkeypatch.setattr(
        sys, "argv", ["/bin/flexmeasures", "add", "account", "--name", "XCorp."]
    )
    assert cli_is_running() is True


@pytest.mark.parametrize(
    "now, flag, expected_start, expected_end",
    [
        (
            datetime(2023, 4, 4, 1, 30, tzinfo=utc),
            "last_hour",
            datetime(2023, 4, 4, 0, tzinfo=utc),
            datetime(2023, 4, 4, 1, tzinfo=utc),
        ),
        (
            datetime(2023, 4, 4, 1, 30, tzinfo=utc),
            "last_day",
            datetime(2023, 4, 3, 0, tzinfo=utc),
            datetime(2023, 4, 4, 0, tzinfo=utc),
        ),
        (
            datetime(2023, 4, 8, 1, 30, tzinfo=utc),
            "last_7_days",
            datetime(2023, 4, 1, 0, tzinfo=utc),
            datetime(2023, 4, 8, 0, tzinfo=utc),
        ),
        (
            datetime(2023, 4, 8, 1, 30, tzinfo=utc),
            "last_month",
            datetime(2023, 3, 1, 0, tzinfo=utc),
            datetime(2023, 4, 1, 0, tzinfo=utc),
        ),
        (
            datetime(2023, 1, 1, tzinfo=utc),
            "last_month",
            datetime(2022, 12, 1, tzinfo=utc),
            datetime(2023, 1, 1, tzinfo=utc),
        ),
        (
            datetime(2023, 1, 2, tzinfo=utc),
            "last_year",
            datetime(2022, 1, 1, tzinfo=utc),
            datetime(2023, 1, 1, tzinfo=utc),
        ),
    ],
)
def test_get_timerange_from_flag(monkeypatch, now, flag, expected_start, expected_end):
    import flexmeasures.utils.time_utils as time_utils
    from flexmeasures.cli.utils import get_timerange_from_flag

    # mock server_now to `now`
    monkeypatch.setattr(time_utils, "server_now", lambda: now)

    input_arguments = {flag: True, "timezone": utc}

    start, end = get_timerange_from_flag(**input_arguments)

    assert start == expected_start
    assert end == expected_end


def test_get_unique_sensor_names(app, db, add_asset_with_children):
    from flexmeasures.cli.utils import get_sensor_aliases
    from flexmeasures.cli.data_show import find_duplicates

    sensors = []
    for assets in add_asset_with_children.values():
        for asset in assets.values():
            sensors.extend(asset.sensors)

    duplicates = find_duplicates(sensors, "name")
    aliases = get_sensor_aliases(sensors, duplicates)
    expected_aliases = [
        "power (Test Supplier Account/parent/child_1)",
        "power (Test Supplier Account/parent/child_2)",
        "power (Test Supplier Account/parent)",
        "power (Test Dummy Account/parent/child_1)",
        "power (Test Dummy Account/parent/child_2)",
        "power (Test Dummy Account/parent)",
    ]

    assert list(aliases.values()) == expected_aliases

    duplicates = find_duplicates(sensors, "name")
    aliases = get_sensor_aliases(sensors[:2], duplicates)
    expected_aliases = [
        "power (child_1)",
        "power (child_2)",
    ]

    assert list(aliases.values()) == expected_aliases

    duplicates = find_duplicates(sensors, "name")
    aliases = get_sensor_aliases(sensors[:3], duplicates)
    expected_aliases = [
        "power (parent/child_1)",
        "power (parent/child_2)",
        "power (parent)",
    ]

    assert list(aliases.values()) == expected_aliases


def test_deprecated_options_command_allows_non_deprecated_option():
    @click.command(cls=DeprecatedOptionsCommand)
    @click.option("--name", cls=DeprecatedOption)
    def cmd(name):
        click.echo(name)

    result = CliRunner().invoke(cmd, ["--name", "foo"])

    assert result.exit_code == 0
    assert result.output == "foo\n"


def test_deprecated_options_command_warns_for_deprecated_alias():
    @click.command(cls=DeprecatedOptionsCommand)
    @click.option(
        "--name",
        "--old-name",
        cls=DeprecatedOption,
        deprecated=["--old-name"],
        preferred="--name",
    )
    def cmd(name):
        click.echo(name)

    result = CliRunner().invoke(cmd, ["--old-name", "foo"])

    assert result.exit_code == 0
    assert "Option '--old-name' will be replaced by '--name'." in result.output
    assert result.output.endswith("foo\n")


@pytest.mark.xfail(
    strict=True,
    raises=RuntimeError,
    reason="CustomFlaskCliRunner lets exceptions propagate instead of catching them",
)
def test_custom_cli_runner_raises_exceptions(app):
    """Verify that the custom CLI runner does not catch exceptions.

    This test is expected to fail: CustomFlaskCliRunner propagates exceptions
    raised inside a CLI command instead of swallowing them (as the default runner does).
    If this test unexpectedly passes, it means exceptions are being caught again,
    which would make failing CLI tests much harder to debug.
    """

    @click.command()
    def failing_command():
        raise RuntimeError("This exception should propagate out of the CLI runner")

    runner = app.test_cli_runner()
    runner.invoke(failing_command)


@pytest.mark.parametrize(
    "args, expected_path, expected_message",
    [
        # a plain command, on the group where this was first reported
        (
            ["add", "report", "--start", ""],
            "flexmeasures add report",
            "Invalid value for '--start': Not a valid datetime.",
        ),
        # a DeprecatedOptionsCommand, which passes its own `cls` and so has to inherit the logging
        (
            ["show", "beliefs", "--sensor", "not-an-int"],
            "flexmeasures show beliefs",
            "Invalid value for '--sensor' / '--sensor-id': Not a valid integer.",
        ),
        # a command in a third group, to show this is not specific to one of them
        (
            ["edit", "attribute", "--asset", "not-an-int"],
            "flexmeasures edit attribute",
            "Invalid value for '--asset' / '--asset-id': Not a valid integer.",
        ),
        # the group's own error, rather than one of its commands'
        (
            ["jobs", "run-automation-typo"],
            "flexmeasures jobs",
            "No such command 'run-automation-typo'.",
        ),
    ],
)
def test_cli_logs_click_error_once(app, caplog, args, expected_path, expected_message):
    """A Click error is logged as one line, whichever group it comes from, and Click still reports it itself."""
    runner = app.test_cli_runner()

    with caplog.at_level(logging.ERROR):
        result = runner.invoke(args=args)

    assert result.exit_code == 2
    assert f"Click error in `{expected_path}`: {expected_message}" in caplog.text

    # one line per failure, so that a command failing on every cron run does not fill the log
    assert caplog.text.count("Click error in") == 1

    # the usage block belongs on stderr, where Click puts it, and not in the log
    assert f"Usage: {expected_path} [OPTIONS]" not in caplog.text
    assert "Error: " + expected_message in result.output


def test_cli_does_not_log_when_a_command_succeeds(app, caplog):
    """Nothing is logged for a command that parses its options fine."""
    runner = app.test_cli_runner()

    with caplog.at_level(logging.ERROR):
        result = runner.invoke(args=["add", "report", "--help"])

    assert result.exit_code == 0
    assert "Click error in" not in caplog.text


def test_cli_logs_a_command_body_error_against_that_command(app, caplog):
    """An error raised in a command's body, which carries no context of its own, still names the command rather than its group."""
    runner = app.test_cli_runner()

    with caplog.at_level(logging.ERROR):
        result = runner.invoke(args=["show", "data-sources", "--show-sensors"])

    assert result.exit_code == 2
    assert (
        "Click error in `flexmeasures show data-sources`: --show-sensors requires --id."
        in caplog.text
    )
    assert caplog.text.count("Click error in") == 1


def test_deprecated_options_command_logs_click_errors(caplog):
    """A command passing its own `cls` logs too, which is why DeprecatedOptionsCommand inherits the behaviour."""

    @click.group("group", cls=LoggedClickExceptionGroup)
    def group():
        pass

    @group.command("cmd", cls=DeprecatedOptionsCommand)
    def cmd():
        raise click.UsageError("something the body objected to")

    with caplog.at_level(logging.ERROR):
        result = CliRunner().invoke(group, ["cmd"])

    assert result.exit_code == 2
    assert "Click error in `group cmd`: something the body objected to" in caplog.text
