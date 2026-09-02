.. _automations:

Automations
============

An **automation** is a recurring task defined on an asset.
For now, an automation computes forecasts or schedules; automating reports is planned.

On each run, the automation queues jobs (so make sure a worker is processing the ``forecasting`` or ``scheduling`` queue, whichever the automation needs, see :ref:`redis-queue`).
The parameters of the task were stored when the automation was created, and validated with the same schema that the CLI and API use.
Timing parameters are resolved on each run — for instance, the forecast or schedule start defaults to the time the automation runs, so each run produces fresh results.

Creating an automation
----------------------

Here is how you create an automation in the CLI, asking for daily (at 6 AM) forecasts of sensor 12:

.. code-block:: bash

    flexmeasures add automation --asset 3 --name "Daily PV forecasts" --type forecasting \
        --cron "0 6 * * *" --timezone Europe/Amsterdam --sensor 12

``--type`` says which task to automate (``forecasting`` or ``scheduling``, matching the queue the jobs go to), and defaults to ``forecasting``.
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

Automating schedules
--------------------

A schedule automation's parameters form a schedule trigger message, as accepted by the `[POST] /assets/(id)/schedules/trigger <../api/v3_0.html#post--api-v3_0-assets-id-schedules-trigger>`_ API endpoint (without the asset id).
Use the canonical API field names, including ``flex-model``, ``flex-context`` and ``force-new-job-creation``.
The message is passed in a file, through ``--parameters``, and validated when the automation is created.
No forecaster or data source is involved, so the forecaster options above do not apply to a schedule automation, and are refused when combined with ``--type scheduling``.

Omit the ``start`` field to calculate it afresh from the server time on each run.
It is floored to the fixed, positive ``resolution`` when given, or otherwise to the minute.
A fixed ``start`` is accepted, but every run then schedules the same period and the CLI warns about this when creating the automation.
The ``duration`` must be positive; ``resolution`` does not accept nominal durations such as a month.
As usual, the flex-context and flex-model can also (partly) live on the asset itself, in which case a minimal trigger message suffices.

For example, this automation queues a scheduling job every hour, each time scheduling the next 12 hours:

.. code-block:: bash

    echo 'duration: "PT12H"' > trigger-message.yml
    flexmeasures add automation --asset 3 --name "Hourly schedules" --cron "0 * * * *" --type scheduling --parameters trigger-message.yml

Running automations
-------------------

For automations to actually run, let a cron job execute the following command once per minute:

.. code-block:: bash

    * * * * * flexmeasures jobs run-automations

Each due automation then queues its jobs.
If the runner misses runs, because it was down or overloaded, it catches up when it resumes: it queues only the latest missed run of each automation, rather than replaying stale ones.
Timing parameters that default to the run time are resolved when that catch-up run is queued, so it produces a current forecast or schedule.

Each scheduled run receives at most one automatic queueing attempt.
If the process crashes, or queueing fails after creating some jobs, that run is not retried automatically, because a retry could duplicate partial work.

The jobs record how they were created, which is shown on the asset's status page (UI), where recent jobs are listed.

Viewing automations
-------------------

Automations defined on an asset can be viewed on the asset's *Automations* page in the UI, and listed with the API endpoint `[GET] /assets/(id)/automations <../api/v3_0.html#get--api-v3_0-assets-id-automations>`_.
An automation's details show the sensors it reads from and writes to, linking to each sensor's page.
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

Keeping a single moving timestamp, rather than a record per run, is what makes the behaviour above fall out: a runner that has been down catches up by moving the cursor straight to the latest due run, and two runners started in the same minute cannot queue the same run twice, because the cursor is advanced with a conditional update that only one of them can win.

A new automation starts from its creation minute and does not replay runs from before it existed.
Changing its cron expression or timezone, or reactivating it, restarts from the time of that change.
Deactivated automations do not accumulate catch-up work.
After upgrading an existing installation, runs scheduled before the upgrade are not replayed.

Daylight-saving-time transitions follow wall-clock semantics.
If the clock skips a scheduled local time in spring, that run happens once at the transition boundary.
If a scheduled local time occurs twice in autumn, the first instance is the canonical run and the repeated instance is not queued again.
