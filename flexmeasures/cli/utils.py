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


class MsgStyle(object):
    """Stores the text styles for the different events

    Styles options are the attributes of the `click.style` which can be found
    [here](https://click.palletsprojects.com/en/8.1.x/api/#click.style).

    """

    SUCCESS: dict[str, Any] = {"fg": "green"}
    WARN: dict[str, Any] = {"fg": "yellow"}
    ERROR: dict[str, Any] = {"fg": "red"}


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
    timezone: pytz.BaseTzInfo = get_timezone(),
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
