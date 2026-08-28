.. _automations:

Automations
============

An **automation** is a recurring task defined on an asset.
For now, an automation computes forecasts; automating schedules and reports is planned.

On each run, the automation queues jobs (so make sure a worker is processing the ``forecasting`` queue, see :ref:`redis-queue`).
The parameters of the task were stored when the automation was created, and validated with the same schema that the CLI and API use.
Timing parameters are resolved on each run — for instance, the forecast start defaults to the time the automation runs, so each run produces fresh forecasts.

Creating an automation
----------------------

Here is how you create an automation in the CLI, asking for daily (at 6 AM) forecasts of sensor 12:

.. code-block:: bash

    flexmeasures add automation --asset 3 --name "Daily PV forecasts" --type forecasts \
        --cron "0 6 * * *" --timezone Europe/Amsterdam --sensor 12

``--type`` says what the automation computes, and defaults to ``forecasts``.
The remaining options are the ones the task itself needs: a forecast automation accepts everything `flexmeasures add forecast` accepts, such as ``--forecaster`` to pick the forecaster and ``--config`` to configure it (see :ref:`forecasting`).
The forecaster and its configuration are stored on a data source, so you can also pass ``--source`` to reuse the data source of an existing forecaster, in which case ``--forecaster`` and ``--config`` (and the individual configuration options) are not needed — the data source already determines them.
That data source is required while the automation exists, so it cannot be deleted until the automation is removed.

The recurrence is defined by a standard five-field cron string (minute, hour, day of month, month, and day of week), which defaults to ``"0 0 * * *"`` (daily at midnight).
It is interpreted in the automation's IANA timezone.
If ``--timezone`` is omitted, the current ``FLEXMEASURES_TIMEZONE`` value is copied to the automation.
Changing that configuration later does not change existing automations.
Cron aliases and optional seconds or year fields are not supported.

Automations are active by default (use ``--inactive`` to create them in deactivated state).
Use ``flexmeasures edit automation`` to rename, re-schedule (``--cron``), change the timezone, activate or deactivate an automation, and ``flexmeasures delete automation`` to remove one.
These changes are recorded in the asset's audit log.

For forecast automations, the sensor on which forecasts are saved (``sensor-to-save``, falling back to ``sensor``) must belong to the automation's asset or one of its descendants.
This relationship is checked both when the automation is created and immediately before each run.

Running automations
-------------------

For automations to actually run, let a cron job execute the following command once per minute:

.. code-block:: bash

    * * * * * flexmeasures jobs run-automations

Each due automation then queues its jobs.
If the runner misses runs, because it was down or overloaded, it catches up when it resumes: it queues only the latest missed run of each automation, rather than replaying stale ones.
Timing parameters that default to the run time are resolved when that catch-up run is queued, so it produces a current forecast.

Each scheduled run a runner picks up is recorded durably, so a queueing attempt which fails can be retried without duplicating the jobs it already created.
See :ref:`automation_runs`.

The jobs record how they were created, which is shown on the asset's status page (UI), where recent jobs are listed.

.. _automation_runs:

Runs and retries
----------------

Every scheduled run a runner picks up gets a record in the database, which outlives the jobs it creates (jobs in Redis expire).
The runner claims the run before doing any work, and the database allows only one record per automation, scheduled time and schedule revision, so two runners started in the same minute cannot both execute it.
A claim comes with a lease: while one runner holds a live lease on a run, no other runner touches it, and once that lease expires the run is up for grabs again, which is how a runner that died mid-queueing hands its work over.

Before queueing anything, the runner writes down the plan for the run: the parameters it will use and the individual jobs it intends to create, each with its own logical name and a job ID derived from the run.
This is what makes a retry safe.
A run which failed before queueing anything is dispatched again in full.
A run which queued only some of its jobs resumes from the same plan, recognizes the jobs already in Redis by their IDs, and queues only the ones still missing, so a retry never duplicates work, and never silently drops it either.
Because the plan is stored, a retry hours later still uses the parameters and timings the run was originally planned with, even if the automation has been edited since.

A run tracks two things separately: how far its *dispatch* got (``pending``, ``claimed``, ``partially_queued``, ``queued`` or ``failed``), and how its *execution* by the workers ended (``pending``, ``running``, ``succeeded``, ``failed`` or ``canceled``).
Each attempt to dispatch a run is recorded too, with the runner which made it, what it queued, and why it failed if it did.
This is what an operator needs to tell a run which failed before queueing anything, one which queued half its work, and one which queued everything but then failed while computing, apart from each other.

Editing an automation's cron string or timezone, or reactivating it, counts up its schedule revision.
Runs of the old and the new schedule therefore stay distinct, even when they fall on the same scheduled UTC time.

Viewing automations
-------------------

Automations defined on an asset can be viewed on the asset's *Automations* page in the UI, and listed with the API endpoint `[GET] /assets/(id)/automations <../api/v3_0.html#get--api-v3_0-assets-id-automations>`_.
An automation's details show the sensors it reads from and writes to, linking to each sensor's page, and summarize its recent runs and their outcomes.
Conversely, a sensor's page lists the automations that write data to it.

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

Keeping a single moving timestamp is what makes the catch-up behaviour above fall out: a runner that has been down catches up by moving the cursor straight to the latest due run, rather than replaying every run it missed.
The cursor also decides who may claim a newly due run, because it is advanced with a conditional update which only one of two runners started in the same minute can win.
What happened to a run once it is claimed is kept in its own record instead (see :ref:`automation_runs`), which is why the cursor alone says nothing about whether queueing or the task succeeded.

A new automation starts from its creation minute and does not replay runs from before it existed.
Changing its cron expression or timezone, or reactivating it, restarts from the time of that change.
Deactivated automations do not accumulate catch-up work.
After upgrading an existing installation, runs scheduled before the upgrade are not replayed.

Daylight-saving-time transitions follow wall-clock semantics.
If the clock skips a scheduled local time in spring, that run happens once at the transition boundary.
If a scheduled local time occurs twice in autumn, the first instance is the canonical run and the repeated instance is not queued again.
