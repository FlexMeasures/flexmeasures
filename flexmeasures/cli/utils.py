"""
Utils for FlexMeasures CLI
"""

from __future__ import annotations

from typing import Any
from datetime import datetime, timedelta

import click
import pytz
from click_default_group import DefaultGroup

from flexmeasures.utils.time_utils import get_most_recent_hour, get_timezone
from flexmeasures.utils.validation_utils import validate_color_hex, validate_url
from flexmeasures import Sensor


class MsgStyle(object):
    """Stores the text styles for the different events

    Styles options are the attributes of the `click.style` which can be found
    [here](https://click.palletsprojects.com/en/8.1.x/api/#click.style).

    """

    SUCCESS: dict[str, Any] = {"fg": "green"}
    WARN: dict[str, Any] = {"fg": "yellow"}
    ERROR: dict[str, Any] = {"fg": "red"}


class DeprecatedOption(click.Option):
    """A custom option that can be used to mark an option as deprecated.

    References
    ----------------

    Copied from  https://stackoverflow.com/a/50402799/13775459
    """

    def __init__(self, *args, **kwargs):
        self.deprecated = kwargs.pop("deprecated", ())
        self.preferred = kwargs.pop("preferred", args[0][-1])
        super(DeprecatedOption, self).__init__(*args, **kwargs)


class DeprecatedOptionsCommand(click.Command):
    """A custom command that can be used to mark options as deprecated.

    References
    ----------------

    Adapted from  https://stackoverflow.com/a/50402799/13775459
    """

    def make_parser(self, ctx):
        """Hook 'make_parser' and during processing check the name
        used to invoke the option to see if it is preferred"""

        parser = super(DeprecatedOptionsCommand, self).make_parser(ctx)

        # get the parser options
        options = set(parser._short_opt.values())
        options |= set(parser._long_opt.values())

        for option in options:
            if not isinstance(option.obj, DeprecatedOption):
                continue

            def make_process(an_option):
                """Construct a closure to the parser option processor"""

                orig_process = an_option.process
                deprecated = getattr(an_option.obj, "deprecated", None)
                preferred = getattr(an_option.obj, "preferred", None)
                msg = "Expected `deprecated` value for `{}`"
                assert deprecated is not None, msg.format(an_option.obj.name)

                def process(value, state):
                    """The function above us on the stack used 'opt' to
                    pick option from a dict, see if it is deprecated"""

                    # reach up the stack and get 'opt'
                    import inspect

                    frame = inspect.currentframe()
                    try:
                        opt = frame.f_back.f_locals.get("opt")
                    finally:
                        del frame

                    if opt in deprecated:
                        click.secho(
                            f"Option '{opt}' will be replaced by '{preferred}'.",
                            **MsgStyle.WARN,
                        )
                    return orig_process(value, state)

                return process

            option.process = make_process(option)

        return parser


class DeprecatedDefaultGroup(DefaultGroup):
    """Invokes a default subcommand, *and* shows a deprecation message.

    Also adds the `invoked_default` boolean attribute to the context.
    A group callback can use this information to figure out if it's being executed directly
    (invoking the default subcommand) or because the execution flow passes onwards to a subcommand.
    By default it's None, but it can be the name of the default subcommand to execute.

    .. sourcecode:: python

        import click
        from flexmeasures.cli.utils import DeprecatedDefaultGroup

        @click.group(cls=DeprecatedDefaultGroup, default="bar", deprecation_message="renamed to `foo bar`.")
        def foo(ctx):
            if ctx.invoked_default:
                click.echo("foo")

        @foo.command()
        def bar():
            click.echo("bar")

    .. sourcecode:: console

        $ flexmeasures foo
        DeprecationWarning: renamed to `foo bar`.
        foo
        bar
        $ flexmeasures foo bar
        bar
    """

    def __init__(self, *args, **kwargs):
        self.deprecation_message = "DeprecationWarning: " + kwargs.pop(
            "deprecation_message", ""
        )
        super().__init__(*args, **kwargs)

    def get_command(self, ctx, cmd_name):
        ctx.invoked_default = None
        if cmd_name not in self.commands:
            click.echo(click.style(self.deprecation_message, fg="red"), err=True)
            ctx.invoked_default = self.default_cmd_name
        return super().get_command(ctx, cmd_name)


def get_timerange_from_flag(
    last_hour: bool = False,
    last_day: bool = False,
    last_7_days: bool = False,
    last_month: bool = False,
    last_year: bool = False,
    timezone: pytz.BaseTzInfo | None = None,
) -> tuple[datetime, datetime]:
    """This function returns a time range [start,end] of the last-X period.
    See input parameters for more details.

    :param bool last_hour: flag to get the time range of the last finished hour.
    :param bool last_day: flag to get the time range for yesterday.
    :param bool last_7_days: flag to get the time range of the previous 7 days.
    :param bool last_month: flag to get the time range of last calendar month
    :param bool last_year: flag to get the last completed calendar year
    :param timezone: timezone object to represent
    :returns: start:datetime, end:datetime
    """

    if timezone is None:
        timezone = get_timezone()

    current_hour = get_most_recent_hour().astimezone(timezone)

    if last_hour:  # last finished hour
        end = current_hour
        start = current_hour - timedelta(hours=1)

    if last_day:  # yesterday
        end = current_hour.replace(hour=0)
        start = end - timedelta(days=1)

    if last_7_days:  # last finished 7 day period.
        end = current_hour.replace(hour=0)
        start = end - timedelta(days=7)

    if last_month:
        end = current_hour.replace(
            hour=0, day=1
        )  # get the first day of the current month
        start = (end - timedelta(days=1)).replace(
            day=1
        )  # get first day of the previous month

    if last_year:  # last calendar year
        end = current_hour.replace(
            month=1, day=1, hour=0
        )  # get first day of current year
        start = (end - timedelta(days=1)).replace(
            day=1, month=1
        )  # get first day of previous year

    return start, end


def validate_unique(ctx, param, value):
    """Callback function to ensure multiple values are unique."""
    if value is not None:
        # Check if all values are unique
        if len(value) != len(set(value)):
            raise click.BadParameter("Values must be unique.")
    return value


def abort(message: str):
    click.secho(message, **MsgStyle.ERROR)
    raise click.Abort()


def done(message: str):
    click.secho(message, **MsgStyle.SUCCESS)


def path_to_str(path: list, separator: str = ">") -> str:
    """
    Converts a list representing a path to a string format, using a specified separator.
    """

    return separator.join(path)


def are_all_equal(paths: list[list[str]]) -> bool:
    """
    Checks if all given entity paths represent the same path.
    """
    return len(set(path_to_str(p) for p in paths)) == 1


def reduce_entity_paths(asset_paths: list[list[str]]) -> list[list[str]]:
    """
    Simplifies a list of entity paths by trimming their common ancestor.

    Examples:
    >>> reduce_entity_paths([["Account1", "Asset1"], ["Account2", "Asset2"]])
    [["Account1", "Asset1"], ["Account2", "Asset2"]]

    >>> reduce_entity_paths([["Asset1"], ["Asset2"]])
    [["Asset1"], ["Asset2"]]

    >>> reduce_entity_paths([["Account1", "Asset1"], ["Account1", "Asset2"]])
    [["Asset1"], ["Asset2"]]

    >>> reduce_entity_paths([["Asset1", "Asset2"], ["Asset1"]])
    [["Asset1"], ["Asset1", "Asset2"]]

    >>> reduce_entity_paths([["Account1", "Asset", "Asset1"], ["Account1", "Asset", "Asset2"]])
    [["Asset1"], ["Asset2"]]
    """
    reduced_entities = 0

    # At least we need to leave one entity in each list
    max_reduced_entities = min([len(p) - 1 for p in asset_paths])

    # Find the common path
    while (
        are_all_equal([p[:reduced_entities] for p in asset_paths])
        and reduced_entities <= max_reduced_entities
    ):
        reduced_entities += 1

    return [p[reduced_entities - 1 :] for p in asset_paths]


def get_sensor_aliases(
    sensors: list[Sensor],
    reduce_paths: bool = True,
    separator: str = "/",
) -> dict:
    """
    Generates aliases for all sensors by appending a unique path to each sensor's name.

    Parameters:
    :param sensors:         A list of Sensor objects.
    :param reduce_paths:    Flag indicating whether to reduce each sensor's entity path. Defaults to True.
    :param separator:       Character or string used to separate entities within each sensor's path. Defaults to "/".

    :return: A dictionary mapping sensor IDs to their generated aliases.
    """

    entity_paths = [
        s.generic_asset.get_path(separator=separator).split(separator) for s in sensors
    ]
    if reduce_paths:
        entity_paths = reduce_entity_paths(entity_paths)
    entity_paths = [path_to_str(p, separator=separator) for p in entity_paths]

    aliases = {
        sensor.id: f"{sensor.name} ({path})"
        for path, sensor in zip(entity_paths, sensors)
    }

    return aliases


def validate_color_cli(ctx, param, value):
    """
    Optional parameter validation

    Validates that a given value is a valid hex color code.

    Parameters:
    :param ctx:     Click context.
    :param param:   Click parameter name.
    :param value:   The color code to validate.
    """

    try:
        validate_color_hex(value)
    except ValueError as e:
        click.secho(str(e), **MsgStyle.ERROR)
        raise click.Abort()


def validate_url_cli(ctx, param, value):
    """
    Optional parameter validation

    Validates that a given value is a valid URL format using regex.

    Parameters:
    :param ctx:     Click context.
    :param param:   Click parameter name.
    :param value:   The URL to validate.
    """

    try:
        validate_url(value)
    except ValueError as e:
        click.secho(str(e), **MsgStyle.ERROR)
        raise click.Abort()
