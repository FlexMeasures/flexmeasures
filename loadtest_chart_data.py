"""Concurrent load test for the chart-data endpoint.

Fires N simultaneous requests and reports throughput, latency percentiles, and
the server-reported DB time (from the Server-Timing header, when
FLEXMEASURES_PROFILE_DB_QUERIES is on). Run it once with the materialized view
active and once without to see the difference under concurrency.

Usage:
    FM_EMAIL=you@example.com FM_PASSWORD=secret \
    FM_ASSET=1092 FM_CONCURRENCY=100 \
    FM_START=2025-06-02T00:00:00+02:00 FM_END=2025-06-03T00:00:00+02:00 \
    python loadtest_chart_data.py
"""

import os
import time
import statistics
import concurrent.futures as cf

import requests

BASE = os.environ.get("FM_BASE", "http://127.0.0.1:5000")
EMAIL = os.environ["FM_EMAIL"]
PASSWORD = os.environ["FM_PASSWORD"]
ASSET = int(os.environ.get("FM_ASSET", "1092"))
N = int(os.environ.get("FM_CONCURRENCY", "100"))
# Keep the range short so the request is DB-bound (a full year is serialization-bound).
START = os.environ.get("FM_START", "2025-06-02T00:00:00+02:00")
END = os.environ.get("FM_END", "2025-06-03T00:00:00+02:00")

token = requests.post(
    f"{BASE}/api/v3_0/requestAuthToken", json={"email": EMAIL, "password": PASSWORD}
).json()["auth_token"]
headers = {"Authorization": token}
url = f"{BASE}/api/v3_0/assets/{ASSET}/chart_data"
params = {
    "event_starts_after": START,
    "event_ends_before": END,
    "compress_json": "true",
}


def one_request(_):
    t0 = time.perf_counter()
    r = requests.get(url, params=params, headers=headers)
    latency_ms = (time.perf_counter() - t0) * 1000
    db_ms = None
    st = r.headers.get("Server-Timing", "")
    if "dur=" in st:
        try:
            db_ms = float(st.split("dur=")[1].split(";")[0])
        except ValueError:
            pass
    return latency_ms, db_ms, r.status_code


def pct(sorted_vals, p):
    return sorted_vals[min(len(sorted_vals) - 1, int(len(sorted_vals) * p))]


# small warm-up so pools/caches are primed
one_request(0)

t0 = time.perf_counter()
with cf.ThreadPoolExecutor(max_workers=N) as ex:
    results = list(ex.map(one_request, range(N)))
wall = time.perf_counter() - t0

lat = sorted(r[0] for r in results)
dbs = [r[1] for r in results if r[1] is not None]
ok = sum(1 for r in results if r[2] == 200)

print(f"asset {ASSET}  range {START} .. {END}")
print(f"{N} concurrent requests, {ok}/{N} ok")
print(f"wall {wall:.2f}s   throughput {N / wall:.1f} req/s")
print(
    f"client latency ms:  p50 {pct(lat, .5):.0f}  p95 {pct(lat, .95):.0f}  max {lat[-1]:.0f}"
)
if dbs:
    dbs.sort()
    print(
        f"server DB time ms:  p50 {statistics.median(dbs):.0f}  p95 {pct(dbs, .95):.0f}  max {dbs[-1]:.0f}"
    )
