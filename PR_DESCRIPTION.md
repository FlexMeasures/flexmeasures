## Description

- Squash the 120 pre-release migrations into a single baseline (`812621895c9c`), so a new database
  builds its structure in one step. Old files move unchanged to `versions_legacy/`, only used to
  upgrade an existing database before it's stamped at the baseline; `flexmeasures db upgrade`
  picks the right path on its own.
- New migrations go in `versions_current/`, UTC-timestamped filenames so the head is just the last
  filename. Downgrading past the baseline is refused with a clear error.
- Startup reads the expected revision from that filename instead of building an Alembic
  `ScriptDirectory` (which imports every migration module) — cuts an avoidable import per boot.
- Extracted `_check_database_schema_revision()` out of `register_at()` for direct unit testing.
- Added `flexmeasures/data/scripts/check_migration_baseline.py`: Docker-only local script that
  seeds a DB at the legacy root and checks the upgrade reaches current head. Not run in CI (a few
  minutes to walk all 120 legacy revisions).
- [x] Added changelog item in `documentation/changelog.rst`

## Look & Feel

N/A, no UI/API/CLI-visible change.

## How to test

- `uv run pytest flexmeasures/data/tests/test_migration_trees.py flexmeasures/data/tests/test_utils.py`
- `uv run flexmeasures/data/scripts/check_migration_baseline.py` — full legacy-root-to-head upgrade
  check in a throwaway Docker Postgres.

### Benchmark

Fresh-install boot (empty DB, full `db upgrade`), `main` vs. this branch, Docker + hyperfine:

```
main:        20.95s mean (median 20.97s, n=5)
this branch: 20.06s mean (median 20.06s, n=5)
```

~0.9s faster, consistent. Isolated `db upgrade`: 7.4–8.6s (120 legacy revisions) vs. 6.76–6.85s (2
revisions from baseline) — fixed per-invocation overhead dominates over revision count. Warm boot
and memory: no measurable difference from `main`, as expected. Full writeup in
`BOOT_TIME_INVESTIGATION.md`.

## Further Improvements

- Found and worked around a real pre-existing deadlock in the legacy upgrade path
  (`ad98460751d9`→`521034349543`, a second connection blocking on the main transaction's lock when
  many revisions run in one Alembic transaction). Worked around in the check script by walking one
  revision at a time; not fixed in the migration files themselves.

## Related Items

Independent perf work surfaced while benchmarking this PR (not included here):
FlexMeasures#2512, FlexMeasures#2514, SeitaBV/timely-beliefs#246, SeitaBV/timely-beliefs#252.

---

#### Sign-off

- [x] I agree to contribute to the project under Apache 2 License.
- [x] To the best of my knowledge, the proposed patch is not based on code under GPL or other
  license that is incompatible with FlexMeasures
