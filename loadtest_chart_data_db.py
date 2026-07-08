"""In-process concurrent load test for the chart-data DB path (no server, no auth).

Fires N concurrent chart_data_json() calls (each on its own DB session/connection)
and reports throughput and latency percentiles. Run once with the view and once
without to see the difference under concurrency.

    # base table (always works):
    FM_USE_MVIEW=false FM_CONCURRENCY=100 .venv/bin/python loadtest_chart_data_db.py

    # materialized view (requires it to be refreshed first, see note below):
    FM_USE_MVIEW=true  FM_CONCURRENCY=100 .venv/bin/python loadtest_chart_data_db.py

NOTE: For the FM_USE_MVIEW=true run to actually use the view, it must be activated
by a recorded refresh: run `flexmeasures db-ops refresh-materialized-views` once.
Otherwise get_mview_cutoff() is None and the code falls back to the base table
(so both runs would look identical).

Keep the range short (default: 1 day) so the request is DB-bound; a full year is
dominated by Python JSON serialization and hides the DB difference.
"""

import os
import time
import concurrent.futures as cf
from datetime import datetime

from flexmeasures.app import create
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.config import db

ASSET = int(os.environ.get("FM_ASSET", "1092"))
N = int(os.environ.get("FM_CONCURRENCY", "100"))
USE_MVIEW = os.environ.get("FM_USE_MVIEW", "true").lower() == "true"
START = datetime.fromisoformat(os.environ.get("FM_START", "2025-06-02T00:00:00+02:00"))
END = datetime.fromisoformat(os.environ.get("FM_END", "2025-06-03T00:00:00+02:00"))

app = create()
app.config["FLEXMEASURES_PROFILE_REQUESTS"] = False
# Make sure the connection pool can serve N concurrent workers (else they queue).
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_size": N + 5,
    "max_overflow": 10,
    "pool_timeout": 60,
}


def worker(_):
    with app.app_context():
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


worker(0)  # warm up (prime pool/caches)

t0 = time.perf_counter()
with cf.ThreadPoolExecutor(max_workers=N) as ex:
    latencies = sorted(ex.map(worker, range(N)))
wall = time.perf_counter() - t0

print(
    f"asset {ASSET}  range {START.date()} .. {END.date()}  use_materialized_view={USE_MVIEW}"
)
print(f"{N} concurrent requests   wall {wall:.2f}s   throughput {N / wall:.1f} req/s")
print(
    f"latency ms:  p50 {pct(latencies, .5):.0f}  p95 {pct(latencies, .95):.0f}  max {latencies[-1]:.0f}"
)
