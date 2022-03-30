import sys

from flask import Flask


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
    """
    cli_sets = ("add", "delete", "show", "monitor", "jobs", "db-ops")
    command_line = " ".join(sys.argv)
    for cli_set in cli_sets:
        if f"flexmeasures {cli_set}" in command_line:
            return True
    return False
