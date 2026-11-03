"""Gunicorn server hooks for the container image.

`--preload` loads ``wsgi:application`` once, in gunicorn's parent process, before forking the workers,
so the app's imports (SQLAlchemy, Flask-Security, every configured plugin) run once instead of once per worker.
That import also opens the SQLAlchemy engine's connection pool in the parent process;
forked workers inherit its file descriptors,
and without disposing of it here they'd share live connections across processes,
corrupting query results under concurrent load.
Disposing in ``post_fork`` forces each worker to open its own connections on first use.
It passes ``close=False``, so the worker drops the inherited connections without closing them,
which would also end them for the parent process that still holds them.
"""


def when_ready(server):
    # Gunicorn calls this before forking the first workers.
    # With --preload, the app has used the database by now, and the master would keep those connections for its whole lifetime without ever using them again.
    # Without --preload, the master has no app, and importing wsgi here would create one, so leave it be.
    if not server.cfg.preload_app:
        return
    from flexmeasures.data.config import db
    from wsgi import application

    with application.app_context():
        db.engine.dispose()


def post_fork(_server, _worker):
    # Imported here, not at module level:
    # gunicorn loads this config file before --preload loads the app,
    # and importing wsgi at module level would trigger a second, redundant create_app().
    from flexmeasures.data.config import db
    from wsgi import application

    with application.app_context():
        db.engine.dispose(close=False)
