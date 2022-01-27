from flask import Flask


def register_at(app: Flask):

    if app.cli:
        with app.app_context():
            import flexmeasures.cli.jobs
            import flexmeasures.cli.monitor
            import flexmeasures.cli.data_add
            import flexmeasures.cli.data_show
            import flexmeasures.cli.data_delete
            import flexmeasures.cli.db_ops
            import flexmeasures.cli.testing  # noqa: F401
