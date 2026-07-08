"""Multiprocess concurrent load test for the chart-data DB path (no server, no auth).

Unlike the threaded version, this uses real worker PROCESSES, so Python work runs
in parallel and the database becomes the shared/contended resource — which is
where the materialized view's benefit shows up. Concurrency level = FM_WORKERS.

    FM_USE_MVIEW=false FM_WORKERS=8 FM_REQUESTS=100 .venv/bin/python loadtest_chart_data_mp.py
    FM_USE_MVIEW=true  FM_WORKERS=8 FM_REQUESTS=100 .venv/bin/python loadtest_chart_data_mp.py

Requires the view to be refreshed (`flexmeasures db-ops refresh-materialized-views`)
for the FM_USE_MVIEW=true run. Keep the range short so it stays DB-bound.
"""

import os
import time
import concurrent.futures as cf
from datetime import datetime

ASSET = int(os.environ.get("FM_ASSET", "1092"))
TOTAL = int(os.environ.get("FM_REQUESTS", "100"))
WORKERS = int(os.environ.get("FM_WORKERS", str(os.cpu_count() or 8)))
USE_MVIEW = os.environ.get("FM_USE_MVIEW", "true").lower() == "true"
START = datetime.fromisoformat(os.environ.get("FM_START", "2025-06-02T00:00:00+02:00"))
END = datetime.fromisoformat(os.environ.get("FM_END", "2025-06-03T00:00:00+02:00"))

_app = None


def _init():
    global _app
    from flexmeasures.app import create

    _app = create()
    _app.config["FLEXMEASURES_PROFILE_REQUESTS"] = False


def _work(_):
    from flexmeasures.data.models.generic_assets import GenericAsset
    from flexmeasures.data.config import db

    with _app.app_context():
        asset = db.session.get(GenericAsset, ASSET)
        t0 = time.perf_counter()
        asset.chart_data_json(
            event_starts_after=START,
            event_ends_before=END,
            compress_json=True,
            use_materialized_view=USE_MVIEW,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        db.session.remove()
        return latency_ms


def pct(sorted_vals, p):
    return sorted_vals[min(len(sorted_vals) - 1, int(len(sorted_vals) * p))]


if __name__ == "__main__":
    t0 = time.perf_counter()
    with cf.ProcessPoolExecutor(max_workers=WORKERS, initializer=_init) as ex:
        latencies = sorted(ex.map(_work, range(TOTAL)))
    wall = time.perf_counter() - t0
    print(
        f"use_materialized_view={USE_MVIEW}  {TOTAL} requests across {WORKERS} processes  "
        f"range {START.date()}..{END.date()}"
    )
    print(
        f"wall {wall:.2f}s   throughput {TOTAL / wall:.1f} req/s   "
        f"p50 {pct(latencies, .5):.0f}ms  p95 {pct(latencies, .95):.0f}ms  max {latencies[-1]:.0f}ms"
    )
