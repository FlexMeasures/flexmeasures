.. _automations:

Automations
============

Hosts and users often want the three main FlexMeasures features — :ref:`forecasting`, :ref:`scheduling` and :ref:`reporting` — to run on a recurring basis, across larger numbers of sites.
*Automations* make that a first-class concept: an automation is a recurring task defined on an asset, and each time it runs, it queues jobs.

An automation consists of:

- a **type**: ``forecasts``, ``schedules`` or ``reports``;
- a **recurrence**: a cron string (e.g. ``"0 6 * * *"`` for daily at 6 AM), interpreted in the automation's own IANA timezone;
- a **data generator** (for forecasts and reports): the forecaster or reporter class and its configuration, stored on a data source.
  The data source stays the same across runs, so all results the automation produces attribute to one steady source;
- **parameters**: what to compute on each run, validated by the same schema the CLI and API use for one-off runs.
  Timing parameters are resolved freshly on each run, so a recurring automation always computes fresh periods
  (see the type-specific sections below for the exact rules);
- an **activation status**: only active automations run.

Managing automations
--------------------

Automations can be managed in three ways:

- **CLI**: ``flexmeasures add automation``, ``flexmeasures edit automation`` (name, cron string, timezone and activation status) and ``flexmeasures delete automation``.
- **API**: list and inspect with ``[GET] /assets/(id)/automations`` and ``[GET] /assets/(id)/automations/(automation_id)``;
  create, update and delete with ``[POST|PATCH|DELETE]`` on the same paths (see the `API documentation <../api/v3_0.html>`_).
- **UI**: each asset has an *Automations* page (in the breadcrumbs dropdown), with a tab per automation type.
  It lists each automation's recurrence and recent job counts, and lets you create, edit, (de)activate and delete automations.

Creating, updating and deleting automations requires account admin or consultant rights, and is recorded in the asset's audit log.

Running automations
--------------------

An automation is due whenever its cron string matches the current minute in its configured timezone. To actually run due automations, let a cron job execute the following command once per minute:

.. code-block:: bash

    * * * * * flexmeasures jobs run-automations

Each due automation then queues its jobs — so make sure workers are processing the relevant queues (``forecasting``, ``scheduling`` and/or ``reporting``, see :ref:`redis-queue`).
Each scheduled run receives at most one automatic queueing attempt, so the command is safe to run more than once within a minute.
If the process crashes, or queueing fails after creating some jobs, that run is not retried automatically, because a retry could duplicate partial work.

If the runner misses runs, because it was down or overloaded, it catches up when it resumes: it queues only the latest missed run of each automation, rather than replaying stale ones.
Timing parameters that default to the run time are resolved when that catch-up run is queued, so it produces a current result.

Jobs record how they were created (via the CLI, the API or an automation), which is shown in the *Created Via* column
of the jobs table on the asset's status page, where recent jobs are listed.

Automating each feature
-----------------------

The parameters stored on an automation follow the same schemas as one-off CLI/API calls, with type-specific rules for resolving timing on each run:

- :ref:`automating_forecasts` — forecast parameters; the forecast start defaults to the run time.
- :ref:`automating_schedules` — a schedule trigger message; omit ``start`` to schedule from the run time.
- :ref:`automating_reports` — report parameters; use ``start-offset``/``end-offset`` (Pandas offsets) for a rolling window,
  or omit timing fields to report on the period since the last successfully covered report window.

.. _automation_cursor:

Appendix: how the runner decides what is due
--------------------------------------------

This section describes the bookkeeping behind the catch-up behaviour above.
You do not need it to use automations.

The runner is a stateless command, executed once a minute by cron, so it needs a durable record of how far each automation has got.
That record is one UTC timestamp per automation, its *cursor*: the scheduled time of the most recent run the automation has committed to.
Runs at or before the cursor are never queued again.
Before queueing any jobs, the runner advances the cursor to the run it is about to queue, and saves it.
The cursor therefore records that a run was claimed, not that queueing or the task itself succeeded.

Keeping a single moving timestamp, rather than a record per run, is what makes the behaviour above fall out: a runner that has been down catches up by moving the cursor straight to the latest due run, and two runners started in the same minute cannot queue the same run twice, because the cursor is advanced with a conditional update that only one of them can win.

A new automation starts from its creation minute and does not replay runs from before it existed.
Changing its cron expression or timezone, or reactivating it, restarts from the time of that change.
Deactivated automations do not accumulate catch-up work.
After upgrading an existing installation, runs scheduled before the upgrade are not replayed.

Daylight-saving-time transitions follow wall-clock semantics.
If the clock skips a scheduled local time in spring, that run happens once at the transition boundary.
If a scheduled local time occurs twice in autumn, the first instance is the canonical run and the repeated instance is not queued again.
