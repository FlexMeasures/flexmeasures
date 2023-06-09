"""
CLI functions for FlexMeasures hosts.
"""

import sys

from flask import Flask, current_app


def register_at(app: Flask):

    if app.cli:
        with app.app_context():
            import flexmeasures.cli.jobs
            import flexmeasures.cli.monitor
            import flexmeasures.cli.data_add
            import flexmeasures.cli.data_edit
            import flexmeasures.cli.data_show
            import flexmeasures.cli.data_delete
            import flexmeasures.cli.db_ops
            import flexmeasures.cli.testing  # noqa: F401


def is_running() -> bool:
    """
    True if we are running one of the custom FlexMeasures CLI commands.

    We use this in combination with authorization logic, e.g. we assume that only sysadmins run commands there,
    but also we consider forecasting & scheduling jobs to be in that realm, as well.

    This tooling might not live forever, as we could evolve into a more sophisticated auth model for these cases.
    For instance, these jobs are queued by the system, but caused by user actions (sending data), and then they are run by the system.

    See also: the run_as_cli test fixture, which uses the (non-public) PRETEND_RUNNING_AS_CLI env setting.

    """
    cli_sets = current_app.cli.list_commands(ctx=None)
    command_line = " ".join(sys.argv)
    for cli_set in cli_sets:
        if f"flexmeasures {cli_set}" in command_line:
            return True
    if current_app.config.get("PRETEND_RUNNING_AS_CLI", False):
        return True
    return False
