.. _automations:

Automations
============

An **automation** is a recurring task defined on an asset.
An automation computes forecasts, schedules or reports.

On each run, the automation queues jobs (so make sure a worker is processing the ``forecasting``, ``scheduling`` or ``reporting`` queue, whichever the automation needs, see :ref:`redis-queue`).
The parameters of the task were stored when the automation was created, and validated with the same schema that the CLI and API use.
Timing parameters are resolved on each run — for instance, the forecast or schedule start defaults to the time the automation runs, so each run produces fresh results (see :ref:`automation_timing`).

Creating an automation
----------------------

Here is how you create an automation in the CLI, asking for daily (at 6 AM) forecasts of sensor 12:

.. code-block:: bash

    flexmeasures add automation --asset 3 --name "Daily PV forecasts" --type forecasting \
        --cron "0 6 * * *" --timezone Europe/Amsterdam --sensor 12

``--type`` says which task to automate (``forecasting``, ``scheduling`` or ``reporting``, matching the queue the jobs go to), and defaults to ``forecasting``.
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

.. _automation_timing:

Timing each run
---------------

An automation runs again and again, so its parameters cannot pin a moment in time:
a fixed ``start`` or ``end`` would have every run compute the same period,
and a fixed ``prior`` would have every run ignore the data recorded since then.
All three are refused when the automation is created, whatever its type.
A forecast automation can still fix ``train-start``, where its training data begins, which is part of the forecaster's configuration.

Instead, say how the period a run covers relates to that run, with two of these fields:

- ``start-offset``: where the period starts, as comma-separated Pandas offsets, plus ``DB`` (day begin) and ``HB`` (hour begin);
- ``end-offset``: where the period ends, in the same notation;
- ``duration``: how long the period lasts, as an ISO 8601 duration.

The offsets apply to the time the run was due, on the automation's own clock, the one its cron string is read in.
For instance, an automation due every day at noon, with ``start-offset: "1D,DB"`` and ``duration: "P1D"``, covers the whole of the next day.
A run that only happens after midnight, because the runner was delayed, still covers the day after the one it was due on.
A duration counts real time, so on the day the clocks go forward, ``P1D`` from midnight ends at 1 AM;
two offsets, such as ``"1D,DB"`` and ``"2D,DB"``, follow the calendar day instead.
An automation's forecast is believed at the time it is computed, also when the period it covers starts later.

An offset can also be given alone.
A ``start-offset`` alone gives a forecast or schedule its default duration, and has a report end at the time of the run.
An ``end-offset`` alone is for reports only, which then start where the last successful report ended.

Without offsets, a forecast starts at the time of the run, rounded down to its sensor's resolution,
a schedule starts at the time of the run, rounded down to its ``resolution`` or else to the minute,
and a report covers the period since the last successful report ended (see :ref:`automation_reports`).
The difference shows after the runner was down.
It catches up with only the latest missed run (see :ref:`running_automations`), so offsets then cover the period around that run alone,
while a report without offsets covers everything since the last successful report.

Automating schedules
--------------------

A schedule automation's parameters form a schedule trigger message, as accepted by the `[POST] /assets/(id)/schedules/trigger <../api/v3_0.html#post--api-v3_0-assets-id-schedules-trigger>`_ API endpoint (without the asset id).
Use the canonical API field names, including ``flex-model``, ``flex-context`` and ``force-new-job-creation``.
The message is passed in a file, through ``--parameters``, and validated when the automation is created.
The forecaster options above configure a forecaster, so they do not apply here, and are refused when combined with ``--type scheduling``.

A schedule automation has a data generator too, but you do not name it separately.
It is put together from choices you have already made: the flex config in the trigger message, the flex config saved on the asset tree, and the scheduler that the asset resolves to.
Because those live in two places, and the asset can be edited without touching the automation, the runner puts the generator together again on every run, and moves the automation to another data source when the combination has changed.
Editing an asset's flex-model is therefore a configuration change, and shows up as one: the schedules computed before and after it carry different data sources.

Because the schedule is recomputed on every run, the flex config may only describe the site and its devices, not one moment.
A field with a fixed moment in it, such as ``soc-at-start`` or a ``soc-targets`` entry with a ``datetime``, is refused when the automation is created, and the error names the field.
Refer to a sensor instead, which says where to look rather than what was true once.

Without offsets (see :ref:`automation_timing`), the start is calculated afresh from the server time on each run.
It is floored to the fixed, positive ``resolution`` when given, or otherwise to the minute.
The ``duration`` must be positive; ``resolution`` does not accept nominal durations such as a month.
As usual, the flex-context and flex-model can also (partly) live on the asset itself, in which case a minimal trigger message suffices.

For example, this automation queues a scheduling job every hour, each time scheduling the next 12 hours:

.. code-block:: bash

    echo 'duration: "PT12H"' > trigger-message.yml
    flexmeasures add automation --asset 3 --name "Hourly schedules" --cron "0 * * * *" --type scheduling --parameters trigger-message.yml

And this one schedules the whole of the next day, every day at noon, as for a day-ahead market:

.. code-block:: bash

    printf 'start-offset: "1D,DB"\nduration: "P1D"\n' > day-ahead.yml
    flexmeasures add automation --asset 3 --name "Day-ahead schedules" --cron "0 12 * * *" --timezone Europe/Amsterdam \
        --type scheduling --parameters day-ahead.yml

.. _automation_reports:

Automating reports
------------------

A report automation's parameters are report parameters, as ``flexmeasures add report`` accepts them (see :ref:`reporting`), passed in a file through ``--parameters``.
Name the reporter with ``--reporter``, and configure it with ``--config``.
As for a forecast automation, the reporter and its configuration are stored on a data source, so ``--source`` can reuse the data source of an existing reporter instead.

The sensors a report is recorded on must belong to the automation's asset or one of its descendants.
This is checked when the automation is created and immediately before each run.
A report job only records on those sensors, so a reporter that returns results for any other sensor is refused.

Its period follows :ref:`automation_timing`, with offsets or one offset and a ``duration``.
For instance, ``start-offset: "-1D,DB"`` with ``end-offset: "DB"`` reports on the whole of the previous day.
Without offsets, a report covers the period since the last successful report ended, falling back to the previous cron period on the first run.
That end is recorded by the reporting job itself, once it has succeeded, so a failed report leaves no gap: the next run starts where the last successful one ended.

For example, this automation reports on the previous day, with the offsets above in ``report-parameters.yml``.
It runs every night at 1 AM, an hour after midnight, so that the day's last readings have had time to arrive:

.. code-block:: bash

    flexmeasures add automation --asset 3 --name "Daily self-consumption report" --type reporting \
        --cron "0 1 * * *" --timezone Europe/Amsterdam \
        --reporter PandasReporter --config reporter-config.yml --parameters report-parameters.yml

.. _running_automations:

Running automations
-------------------

For automations to run on schedule, invoke the dispatcher once per minute.
The provided Docker Compose stack does this with its ``automation-runner`` service, which starts after the web server is ready.
If you host FlexMeasures without that service, set up a cron job instead:

.. code-block:: bash

    * * * * * flexmeasures jobs run-automations

Use one dispatcher for a deployment; the Docker Compose service already runs the command, so it does not need a host cron job as well.

Each due automation then queues its jobs.
If the runner misses runs, because it was down or overloaded, it catches up when it resumes: it queues only the latest missed run of each automation, rather than replaying stale ones.
Timing parameters that default to the run time are resolved when that catch-up run is queued, so it produces a current forecast, schedule or report.

Each scheduled run receives at most one automatic queueing attempt.
If the process crashes, or queueing fails after creating some jobs, that run is not retried automatically, because a retry could duplicate partial work.

The jobs record how they were created, which is shown on the asset's status page (UI), where recent jobs are listed.

Running one automation on demand
--------------------------------

Besides its recurring runs, a single automation can be run now, once.
This is useful to try out a new automation, to re-run one after fixing what made it fail, or to refresh its results after late input data arrived.

.. code-block:: bash

    flexmeasures jobs run-automation --automation 4

The same is available in the API, as `[POST] /assets/(id)/automations/(automation_id)/trigger <../api/v3_0.html#post--api-v3_0-assets-id-automations-automation_id-trigger>`_, and in the UI, as the *Run now* button on the asset's *Automations* page.

The automation runs with the parameters it was created with, and the jobs it queues are recorded as its jobs, just like the jobs of a recurring run.
An on-demand run does not affect the automation's recurrence: its cursor (see :ref:`automation_cursor`) stays where it was, so the next recurring run still happens as scheduled, and a run missed while the runner was down is still caught up.
Inactive automations can be run this way, too, which is how you can try one out before activating it.

Unlike a recurring run, an on-demand run is not protected against being started twice: asking for two runs in a row queues two runs.

Viewing automations
-------------------

Automations defined on an asset can be viewed on the asset's *Automations* page in the UI, and listed with the API endpoint `[GET] /assets/(id)/automations <../api/v3_0.html#get--api-v3_0-assets-id-automations>`_.
The page shows the next scheduled run for each automation (excluding any pending catch-up run).
An automation's details show the sensors it reads from and writes to, linking to each sensor's page.
Conversely, a sensor's page lists the automations that write data to it.

.. _automation_cursor:

Appendix: how the runner decides what is due
--------------------------------------------

This section describes the bookkeeping behind the catch-up behaviour above.
You do not need it to use automations.

The runner is a stateless command, executed once a minute by Docker Compose or cron, so it needs a durable record of how far each automation has gotten.
That record is one timestamp per automation, its *cursor*: the scheduled time of the most recent run the automation has committed to.
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
