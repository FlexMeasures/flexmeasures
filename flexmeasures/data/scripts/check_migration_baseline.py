#!/usr/bin/env -S uv run python
"""Check that upgrading a database from the oldest legacy revision reaches the current head.

Seeds a throwaway database at the legacy tree's root, walks it forward one revision at a
time to the legacy head, then runs the same upgrade `flexmeasures db upgrade` would across
the squash cut, and checks it lands on the current tree's head with exactly one
`alembic_version` row.

Walking one revision per `alembic upgrade` call (rather than jumping straight to the legacy
head, which is what `flexmeasures.data.utils.upgrade_database_schema` does) matters: Alembic's
default is one transaction across however many revisions a single call covers, and jumping
means `ad98460751d9`'s `upgrade()` opens a second connection to probe old tables for data,
which then blocks forever on a lock the main connection's still-open transaction already
holds. Real installations never hit this, since they upgraded one release at a time; this
avoids it the same way, rather than working around it with extra transaction management.

Needs only docker: it starts a throwaway Postgres container from this repo's own
`docker-compose.yml` (the `test-db` service), and uses FlexMeasures' own SQLAlchemy/psycopg2
dependency to talk to it, so no client tools need to be on PATH.
Run it with `uv run check_migration_baseline.py`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from flexmeasures.data.utils import get_current_tree_head  # noqa: E402

# Root of the frozen legacy revision tree. A literal because that tree never gains
# another revision, so its root is as permanent as `LEGACY_HEAD` in `flexmeasures/data/utils.py`.
LEGACY_ROOT = "01fe99da5716"

CONTAINER_NAME = "flexmeasures-migration-baseline-pg"
DATABASE = "fm_upgrade_check"

# Matches the `test-db` service in `docker-compose.yml`.
PG = {
    "host": os.environ.get("PGHOST", "127.0.0.1"),
    "port": os.environ.get("PGPORT", "5432"),
    "user": os.environ.get("PGUSER", "fm-test-db-user"),
    "password": os.environ.get("PGPASSWORD", "fm-test-db-pass"),
    "maintenance_db": os.environ.get("PGDB", "fm-test-db"),
}
EXTENSIONS_SQL = REPO_ROOT / "ci" / "load-psql-extensions.sql"


def start_local_postgres() -> None:
    """Start a throwaway `test-db` container from `docker-compose.yml`, published on `PG['port']`."""
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)
    subprocess.run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "-d",
            "--name",
            CONTAINER_NAME,
            "-p",
            f"{PG['port']}:5432",
            "test-db",
        ],
        check=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )
    print("Waiting for Postgres to accept connections ...", flush=True)
    # `pg_isready` via `docker exec` only proves the container's *current* Postgres process
    # is up. The official image restarts internally after running init scripts (a temp
    # server for initdb/extensions, then a real one), so checking readiness that way can
    # pass during the temp server and then race its shutdown. Retrying a real host-side
    # connection instead means we only proceed once the final server actually accepts one.
    deadline = time.monotonic() + 60
    while True:
        try:
            create_engine(uri_for(PG["maintenance_db"])).connect().close()
            break
        except OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


def stop_local_postgres() -> None:
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)


def uri_for(database: str) -> str:
    return f"postgresql://{PG['user']}:{PG['password']}@{PG['host']}:{PG['port']}/{database}"


def execute_sql(database: str, sql: str, *, autocommit: bool = False) -> list[tuple]:
    """Run one SQL statement against `database`, returning any rows it produced.

    `autocommit` is needed for statements Postgres refuses to run inside a transaction,
    such as `CREATE DATABASE`.
    """
    engine = create_engine(uri_for(database))
    try:
        options = {"isolation_level": "AUTOCOMMIT"} if autocommit else {}
        with engine.connect().execution_options(**options) as connection:
            result = connection.execute(text(sql))
            rows = result.fetchall() if result.returns_rows else []
            if not autocommit:
                connection.commit()
            return rows
    finally:
        engine.dispose()


def recreate_database(database: str) -> None:
    """Drop and recreate a throwaway database, with the extensions FlexMeasures expects."""
    execute_sql(
        PG["maintenance_db"], f'DROP DATABASE IF EXISTS "{database}"', autocommit=True
    )
    execute_sql(PG["maintenance_db"], f'CREATE DATABASE "{database}"', autocommit=True)
    for statement in EXTENSIONS_SQL.read_text().splitlines():
        if statement.strip():
            execute_sql(database, statement)


def run_in_subprocess(database: str, body: str) -> None:
    """Run a snippet against a FlexMeasures app in a clean interpreter, streaming its output live.

    A fresh process is what makes the "no legacy module was imported" check mean anything.
    """
    script = textwrap.dedent(f"""
        import os
        os.environ["SQLALCHEMY_DATABASE_URI"] = {uri_for(database)!r}
        os.environ.setdefault("FLEXMEASURES_ENV", "development")
        os.environ.setdefault("SECRET_KEY", "x" * 32)
        from alembic import command as alembic_command
        from flexmeasures.app import create
        from flexmeasures.data import utils as fm_utils

        app = create(env=os.environ["FLEXMEASURES_ENV"])
        with app.app_context():
            migrate = app.extensions["migrate"].migrate
{textwrap.indent(textwrap.dedent(body), " " * 12)}
        """)
    result = subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"Subprocess failed with exit status {result.returncode}.")


def alembic_versions(database: str) -> list[str]:
    rows = execute_sql(
        database, "SELECT version_num FROM alembic_version ORDER BY version_num"
    )
    return [row[0] for row in rows]


def check_upgrade_from_old_migration() -> None:
    """Seed a database at the legacy root, then check the upgrade reaches the current head."""
    print(f"Seeding {DATABASE} at legacy revision {LEGACY_ROOT} ...", flush=True)
    recreate_database(DATABASE)
    print(
        "Walking the legacy chain one revision at a time (this takes a while) ...",
        flush=True,
    )
    run_in_subprocess(
        DATABASE,
        """
        config = fm_utils._flask_migrate_config(migrate, fm_utils.VERSIONS_LEGACY_DIR)
        script = fm_utils._script_directory_for(
            app.extensions["migrate"], fm_utils.VERSIONS_LEGACY_DIR
        )
        revisions = list(script.walk_revisions(base="base", head=fm_utils.LEGACY_HEAD))
        revisions.reverse()
        for step, revision in enumerate(revisions, start=1):
            alembic_command.upgrade(config, revision.revision)
            if step % 10 == 0:
                print(f"... {step}/{len(revisions)} revisions in", flush=True)
        """,
    )

    run_in_subprocess(DATABASE, "fm_utils.upgrade_database_schema(app)")

    head = get_current_tree_head()
    versions = alembic_versions(DATABASE)
    assert versions == [head], f"{DATABASE} ended at {versions} instead of [{head}]."
    print("Upgrade from the legacy root reaches the current head.", flush=True)


if __name__ == "__main__":
    if shutil.which("docker") is None:
        sys.exit("Missing 'docker' on PATH. Install it, then re-run this script.")

    start_local_postgres()
    try:
        check_upgrade_from_old_migration()
        print("OK")
    finally:
        stop_local_postgres()
