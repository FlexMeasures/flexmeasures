"""Gunicorn server hooks for the container image.

`--preload` loads ``wsgi:application`` once in the master before forking workers, so the
app's imports (SQLAlchemy, Flask-Security, every configured plugin) run once instead of once
per worker. That import also opens the SQLAlchemy engine's connection pool in the master;
forked workers inherit its file descriptors, and without disposing of it here they'd share
live connections across processes, corrupting query results under concurrent load. Disposing
in ``post_fork`` forces each worker to open its own connections on first use.
"""

def post_fork(_server, _worker):
    # Imported here, not at module level: gunicorn loads this config file before --preload
    # loads the app, and importing wsgi here would trigger a second, redundant create_app().
    from flexmeasures.data.config import db
    from wsgi import application

    with application.app_context():
        db.engine.dispose()
