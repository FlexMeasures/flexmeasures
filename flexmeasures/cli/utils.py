from typing import Tuple, Mapping, Optional
from datetime import datetime, timedelta


import click
from click_default_group import DefaultGroup


class MsgStyle(object):
    """Stores the text styles for the different events

    Styles options are the attributes of the `click.style` which can be found
    [here](https://click.palletsprojects.com/en/8.1.x/api/#click.style).

    """

    SUCCESS: Mapping = {"fg": "green"}
    WARN: Mapping = {"fg": "yellow"}
    ERROR: Mapping = {"fg": "red"}


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


def get_timerange_from_flags(
    start: Optional[datetime], end: Optional[datetime], timezone, **kwargs
) -> Tuple[Optional[datetime], Optional[datetime]]:

    flags = ["last_hour", "last_day", "last_week", "last_month", "last_year"]

    # if any of the flag in `flags` is passed in kwargs
    if len([kwarg for kwarg in kwargs if kwarg in flags]) > 0:
        end = datetime.now(tz=timezone).replace(microsecond=0, second=0, minute=0)
    else:
        return start, end

    """ Handle different flags """
    if kwargs.get("last_hour"):  # last finished hour
        end = end
        start = end - timedelta(hours=1)

    if kwargs.get("last_day"):  # yesterday
        end = end.replace(hour=0)
        start = end - timedelta(days=1)

    if kwargs.get("last_week"):  # last finished 7 week period.
        end = end.replace(hour=0)
        start = end - timedelta(days=7)

    if kwargs.get("last_month"):
        end = end.replace(hour=0) - timedelta(
            days=end.day
        )  # to get the last day of the previous month
        start = end - timedelta(
            days=end.day - 1
        )  # equivalent to start.day = end.day-end.day +1

    if kwargs.get("last_year"):
        end = end.replace(hour=0) - timedelta(
            days=end.day
        )  # to get the last day of the previous month

    return start, end
