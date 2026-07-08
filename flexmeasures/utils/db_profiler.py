"""Per-request database query profiling.

When ``FLEXMEASURES_PROFILE_DB_QUERIES`` is set, every HTTP request records the
SQL statements it runs and how long each took. The aggregate (query count and
total DB time) is returned to the browser via a standard ``Server-Timing``
header — which the chart performance panel reads and shows next to the network
and render timings — and the individual queries are logged server-side.

This is a development/diagnostic tool (e.g. to compare query cost with and
without the materialized view); it is off by default.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from flask import Flask, g, has_app_context, has_request_context, current_app, request
from sqlalchemy import event
from sqlalchemy.engine import Engine

# Engine listeners are global (they attach to the Engine class), so register them
# only once even if the app factory runs multiple times (e.g. in the test suite).
_listeners_registered = False


def _enabled() -> bool:
    return (
        has_app_context()
        and current_app.config.get("FLEXMEASURES_PROFILE_DB_QUERIES", False)
        and has_request_context()
    )


def _register_engine_listeners() -> None:
    global _listeners_registered
    if _listeners_registered:
        return
    _listeners_registered = True

    @event.listens_for(Engine, "before_cursor_execute")
    def before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        if _enabled():
            conn.info.setdefault("_fm_query_start", []).append(time.perf_counter())

    @event.listens_for(Engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if not _enabled():
            return
        try:
            started = conn.info["_fm_query_start"].pop(-1)
        except (KeyError, IndexError):
            return
        duration_ms = (time.perf_counter() - started) * 1000
        if not hasattr(g, "_fm_db_queries"):
            g._fm_db_queries = []
        g._fm_db_queries.append(
            {"statement": " ".join(statement.split()), "duration_ms": duration_ms}
        )


def register_db_query_profiler(app: Flask) -> None:
    """Attach the DB query profiler to the given app."""
    _register_engine_listeners()

    @app.after_request
    def add_db_timing(response):
        if not app.config.get("FLEXMEASURES_PROFILE_DB_QUERIES", False):
            return response
        queries = getattr(g, "_fm_db_queries", [])
        if not queries:
            return response
        total_ms = sum(q["duration_ms"] for q in queries)
        # Standard Server-Timing header: the browser exposes this on the request's
        # PerformanceResourceTiming entry, which the chart perf panel reads.
        response.headers["Server-Timing"] = (
            f'db;dur={total_ms:.1f};desc="{len(queries)} queries"'
        )
        # Log a summary and write a timestamped report file (skip static assets).
        if all(kw not in request.url for kw in ["/static", "favicon.ico"]):
            current_app.logger.info(
                f"[DB-PROFILE] {len(queries)} queries, {total_ms:.1f} ms total "
                f"for {request.method} {request.path}"
            )
            _write_report_file(queries, total_ms)
        return response


def _write_report_file(queries: list[dict], total_ms: float) -> None:
    """Write one timestamped report file listing every query and its duration.

    Files go to ``db_query_reports/<YYYY-MM-DD>/`` with a filename that includes
    the endpoint and the time of day, so each request produces its own report
    and the creation time is visible from the filename.
    """
    now = datetime.now()
    endpoint = (request.endpoint or "unknown").replace(".", "_").replace("/", "_")
    out_dir = Path("db_query_reports", now.strftime("%Y-%m-%d"))
    out_dir.mkdir(parents=True, exist_ok=True)
    # Time down to microseconds keeps filenames unique within the same second.
    filename = f"db-queries_{endpoint}_{now.strftime('%H-%M-%S-%f')}.txt"

    lines = [
        "DB query report",
        f"Created:      {now.isoformat()}",
        f"Request:      {request.method} {request.url}",
        f"Queries:      {len(queries)}",
        f"Total DB time: {total_ms:.1f} ms",
        "",
        "Queries in execution order (duration | statement):",
        "",
    ]
    for i, q in enumerate(queries, start=1):
        lines.append(f"{i:>4}. {q['duration_ms']:8.1f} ms  {q['statement']}")

    (out_dir / filename).write_text("\n".join(lines) + "\n")
    current_app.logger.info(f"[DB-PROFILE] report written to {out_dir / filename}")
