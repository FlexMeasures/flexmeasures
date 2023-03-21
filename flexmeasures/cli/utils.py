import click
from click_default_group import DefaultGroup


class MsgStyle(object):
    """Stores the text styles for the different events

    Styles options are the attributes of the `click.style` which can be found
    [here](https://click.palletsprojects.com/en/8.1.x/api/#click.style).

    """

    SUCCESS = {"fg": "green"}
    WARN = {"fg": "yellow"}
    ERROR = {"fg": "red"}


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
