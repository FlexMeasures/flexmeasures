---
applyTo: "**"
---
# Running FlexMeasures Locally

## Never run the CLI or the app against a shared configuration

A development configuration may point at a database or a Redis server that others use too:
a shared Redis means queued jobs reach workers running other (possibly older) FlexMeasures code,
and a shared database may hold real data.
Commands such as `flexmeasures add forecasts --as-job` or `flexmeasures jobs run-automations` queue jobs there.

To try a change, use the test suite (it has its own database and Redis database), or isolated local services:

- Postgres and Redis of your own (e.g. Docker containers on non-standard ports),
- a configuration file of your own, naming them,
- and a separate `HOME`, because FlexMeasures also picks up `~/.flexmeasures.cfg` (see `find_flexmeasures_cfg` in `flexmeasures/utils/config_utils.py`).

If you queued something on a shared Redis by accident, delete those jobs, including any deferred jobs that wait for them.

Two test runs at once need a database and a Redis database each: see `testing.instructions.md`.

## Checking a change against plugins

Before changing or removing a function, a model attribute or a CLI option that plugins may use, search the plugins for it.
Local clones are not enough: they can be on an old branch, and several plugin repositories may not be cloned at all.

- `git fetch` each local plugin clone and `git grep` its remote branch, not the working tree.
- Search the organisations' repositories as well, e.g. `gh search code "<symbol>" --owner FlexMeasures`,
  and read the actual call sites, since substring hits are common (`asset_attributes` matches `set_attribute`).
