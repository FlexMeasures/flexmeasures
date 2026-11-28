.. _automations:

Automations
============

An **automation** is a recurring task defined on an asset.
An automation computes forecasts, schedules or reports.
Plugins can register additional types, such as data ingestion, with their own data generators, validation schemas and worker queues.
See :ref:`plugin_automation_types` for the plugin contract.

On each run, the automation queues jobs (so make sure a worker is processing the ``forecasting``, ``scheduling`` or ``reporting`` queue, whichever the automation needs, see :ref:`redis-queue`).
The parameters of the task were stored when the automation was created, and validated with the same schema that the CLI and API use.
Timing parameters are resolved on each run — for instance, the forecast or schedule start defaults to the time the automation runs, so each run produces fresh results (see :ref:`automation_timing`).

Creating an automation
----------------------

In the UI, the *New automation* button on the asset's *Automations* page opens a form for a new automation on that asset.
It asks for the same things as the CLI below: a name, the type, the recurrence and its timezone, the task's parameters, and either an existing data source to reuse or the data generator and its configuration.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_automation_new.png
    :align: center
..    :scale: 40%

|

Here is how you create an automation in the CLI, asking for daily (at 6 AM) forecasts of sensor 12:

.. code-block:: bash

    flexmeasures add automation --asset 3 --name "Daily PV forecasts" --type forecasting \
        --cron "0 6 * * *" --timezone Europe/Amsterdam --sensor 12

``--type`` says which registered task to automate and defaults to ``forecasting``.
Built-in types are ``forecasting``, ``scheduling`` and ``reporting``; plugin types use the identifiers registered by the plugin.
The remaining options are the ones the task itself needs: a forecast automation accepts everything `flexmeasures add forecast` accepts, such as ``--forecaster`` to pick the forecaster and ``--config`` to configure it (see :ref:`forecasting`).
The forecaster and its configuration are stored on a data source, so you can also pass ``--source`` to reuse the data source of an existing forecaster, in which case ``--forecaster`` and ``--config`` (and the individual configuration options) are not needed — the data source already determines them.
That data source is required while the automation exists, so it cannot be deleted until the automation is removed.

The API takes the same choice as the ``source`` field of `[POST] /assets/(id)/automations <../api/v3_0.html#post--api-v3_0-assets-id-automations>`_, which cannot be combined with ``data-generator`` or ``config``.
In the UI, the asset's *Automations* page searches the data sources you may work with, by id, by name and by data generator class, and shows the configuration the picked one stores before you create the automation.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_automation_source_search.png
    :align: center
..    :scale: 40%

|

A data source is yours to work with when it belongs to your organisation, or when an automation you may read already computes under it, which is how a source becomes yours before it has recorded anything.
Those are the sources you may name, and the only ones whose stored configuration you are shown.
Reading a data source is allowed more widely: one that has recorded data on a sensor you may read answers the question of what computed a number you can see.
A source you reach only that way hands over no configuration, because a data generator's configuration names the sensors it runs on, which may be sensors you cannot see at all.
Reusing a source means the results of both automations are recorded under it, so they share one lineage of data.
A schedule automation cannot name a data source, because it works its own out on every run, as described under `Automating schedules`_.

The recurrence is defined by a standard five-field cron string (minute, hour, day of month, month, and day of week), which defaults to ``"0 0 * * *"`` (daily at midnight).
It is interpreted in the automation's IANA timezone.
If ``--timezone`` is omitted, the current ``FLEXMEASURES_TIMEZONE`` value is copied to the automation.
Changing that configuration later does not change existing automations.
Cron aliases and optional seconds or year fields are not supported.

Automations are active by default (use ``--inactive`` to create them in deactivated state).
Use ``flexmeasures edit automation`` to rename, re-schedule (``--cron``), change the timezone, activate or deactivate an automation, and ``flexmeasures delete automation`` to remove one.
These changes are recorded in the asset's audit log.

Editing what an automation computes
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

An automation's parameters, and its data generator and configuration, can be changed afterwards, too:
with ``--parameters``, ``--data-generator``, ``--config`` and ``--source`` on ``flexmeasures edit automation``,
with the same fields on `[PATCH] /assets/(id)/automations/(automation-id) <../api/v3_0.html#patch--api-v3_0-assets-id-automations-automation-id>`_,
and with the parameters and config fields of the *Edit* form on the asset's *Automations* page.
They are checked as on creation, including whether you may use the sensors they name.

A new configuration does not change the data source the automation records under.
It moves the automation to the data source storing that configuration, which is looked up or created as on creation,
and leaves the old data source as it is:
other automations may compute under it, and what it recorded was computed with its configuration.
For example, a forecast automation on data source 120 whose ``train-period`` changes moves to another source, say 121,
so that forecasts made before and after the change can be told apart.
Leaving out ``--data-generator`` or ``--config`` keeps the current one,
and ``--source`` moves the automation to an existing data source instead, under the same rules as on creation.
A schedule automation accepts new parameters only, as its data source follows from the asset (see `Automating schedules`_).

A new configuration replaces the current one as a whole, so it has to repeat any setting to keep.

Every run of an automation checks the access of the user it runs as, who is its creator at first.
The *Edit* form says who that is (*Runs as*), and so do the API (``runs-as``) and ``flexmeasures show automations``.
An edit through the API or the UI leaves that user as it is, so the sensors it names have to pass the access checks of both the editor and that user:
this way, nobody can point the automation at sensors that only they may use, while its runs are checked against someone else.
To have the automation run as you from then on, tick *Run as me* in the *Edit* form, or send ``run-as-me`` with the PATCH request;
the sensors are then checked against your access only, and the switch is written to the asset's audit log.
Use this to take over an automation whose runs are refused, for instance because that user's account was deactivated, or they no longer have access to one of its sensors.

An automation set up through the CLI runs as nobody, as the CLI is trusted, so its runs check nobody's access.
An edit of it through the API or the UI is checked against the editor's access only, and its runs stay unchecked, unless the editor takes it over.
An edit through the CLI is not checked against anyone's access either,
but it warns when the user the automation runs as could not run what it now computes, as every run would then be refused;
``flexmeasures edit automation --run-as <user ID>`` then picks another user to run it as.

Runs before and after such a change are kept apart by a new revision, while the cursor (see :ref:`automation_cursor`) stays where it was, as which runs are due has not changed.
A run planned before the change, including one being retried and the jobs it already queued, still computes with the parameters and the data source it was planned with.
It is checked against the user the automation runs as by the time it runs, though,
so after a switch with *Run as me*, a run planned before it fails if it involves a sensor that only its old definition named, and that you may not use.

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

- ``start-offset``: where the period starts, as an offset chain (see below);
- ``end-offset``: where the period ends, as an offset chain;
- ``duration``: how long the period lasts, as an ISO 8601 duration.

On the command line, ``--start-offset``, ``--end-offset`` and ``--duration`` set the same fields, so no parameters file is needed for them.

An offset chain is a comma-separated list of steps, applied from left to right.
Each step is a `Pandas offset alias <https://pandas.pydata.org/pandas-docs/stable/user_guide/timeseries.html#offset-aliases>`_,
optionally preceded by a count and a sign, or one of two steps FlexMeasures adds.
These are the ones most useful for automations, applied to a run due on Friday 27 March 2026 at noon:

==========  =====================================================================  =================================
Step        Moves to                                                               Example result
==========  =====================================================================  =================================
``DB``      the beginning of the day (FlexMeasures)                                27 March, 00:00
``HB``      the beginning of the hour (FlexMeasures)                               27 March, 12:00
``min``     minutes later, or earlier with a minus sign                            ``-30min``: 27 March, 11:30
``h``       hours later or earlier                                                 ``-2h``: 27 March, 10:00
``D``       days later or earlier, of 24 hours each                                ``1D``: 28 March, 12:00
``B``       business days later or earlier                                         ``1B``: 30 March, 12:00
``W``       the next Sunday, so use ``7D`` for a week                              ``1W``: 29 March, 12:00
``MS``      the start of the next month, or of this one with ``-1MS``              ``-1MS``: 1 March, 12:00
``ME``      the end of this month                                                  ``ME``: 31 March, 12:00
``QS``      the start of the next quarter                                          ``QS``: 1 April, 12:00
``YS``      the start of the next year                                             ``YS``: 1 January 2027, 12:00
==========  =====================================================================  =================================

Steps that move to a boundary, such as ``MS``, keep the time of day, so follow them with ``DB`` to start at midnight: ``-1MS,DB`` is the start of the current month.
Older aliases such as ``H``, ``M`` and ``T`` still work, but Pandas warns that they will be removed; use ``h``, ``ME`` and ``min`` instead.

The offsets apply to the time the run was due, on the automation's own clock, the one its cron string is read in.
For instance, an automation due every day at noon, with ``start-offset: "1D,DB"`` and ``duration: "P1D"``, covers the whole of the next day.
A run that only happens after midnight, because the runner was delayed, still covers the day after the one it was due on.
A duration counts real time, so on the day the clocks go forward, ``P1D`` from midnight ends at 1 AM;
two offsets, such as ``"1D,DB"`` and ``"2D,DB"``, follow the calendar day instead.
A duration in months or years follows the calendar, so ``P1M`` from midnight ends at midnight, a month later.
An automation's forecast is believed at the time its run is dispatched, also when the period it covers starts later,
and it uses only the data recorded by then, also when its jobs wait in the queue for a while.

A single field can also be given alone, where the automation has a default for the rest.
A ``start-offset`` alone gives a forecast or schedule its default duration, and has a report end at the time of the run.
A ``duration`` alone has a forecast or schedule start at the time of the run, and is not enough for a report.
An ``end-offset`` alone is for reports only, which then start where the last successful report ended.
Before the first successful report, such a report covers the cron period before that end.
When the last successful report already reaches that end, as it does for an hourly report up to midnight after its first run of the day, the run has nothing new to report on, and queues no job.

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
That is also why a schedule automation cannot be pinned to a data source you pick: the next run would move it off that source again.

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

    flexmeasures add automation --asset 3 --name "Day-ahead schedules" --cron "0 12 * * *" --timezone Europe/Amsterdam \
        --type scheduling --start-offset 1D,DB --duration P1D

Plugin-defined automations
--------------------------

Create a plugin-defined automation with its registered type identifier and JSON or YAML files:

.. code-block:: bash

    flexmeasures add automation --asset 3 --name "Import site measurements" \
        --type site-ingestion --cron "*/15 * * * *" --timezone Europe/Amsterdam \
        --config ingestion-config.yml --parameters ingestion-parameters.yml

The registered handler determines the data generator and worker queue.
``--data-generator`` can explicitly name the registered generator; ``--source`` reuses an existing generator configuration and cannot be combined with ``--data-generator`` or ``--config``.
Forecast-specific command-line options do not apply to plugin types.
Plugin schemas validate configuration and parameters, and unknown fields are rejected.
Run a worker for the queue declared by the handler, in addition to the automation dispatcher.

The UI lists registered plugin types in their own tabs and shows their parameters, data source, input sensors, output sensors and recent jobs.
Existing actions, including editing recurrence, activation, deletion and *Run now*, also apply to these automations.
Creation forms for plugin types are a follow-up: use the CLI or API to create them for now.

API-created automations remember the user who created them.
The dispatcher and worker recheck that the user is active and can write to the output sensors.
CLI-created automations run as trusted deployment operations.
Every output sensor must still belong to the automation's asset or one of its descendants.

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

.. _critical_automations:

Critical automations
--------------------

Some automations matter more to an organisation than others: a day-ahead schedule that a market
position depends on is not a weekly report. Flag such an automation as critical, and FlexMeasures
hands its failures to whatever your organisation does about them.

.. code-block:: bash

    flexmeasures add automation --asset 3 --name "Day-ahead schedules" --type scheduling \
        --cron "0 12 * * *" --critical --parameters trigger-message.yml

    flexmeasures edit automation --id 4 --critical
    flexmeasures edit automation --id 4 --not-critical

The same flag is the ``critical`` field of the automations API, and a *Critical* checkbox in the
creation and edit forms in the UI, where a critical automation's row carries a ``critical`` badge.
A copy of a critical automation is critical too.

Being critical changes nothing about how an automation runs: the same jobs are queued on the same
recurrence, and a failed dispatch is retried exactly as before (see :ref:`automation_runs`).
It changes only who is told when a run fails.

Hooking into critical failures
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

FlexMeasures takes no view on what a critical failure means for your organisation — one pages the
engineer on duty, another opens a ticket, a third writes to a status page — so it reports the
failure and leaves the business logic to you.

A hook is a callable taking one
:class:`~flexmeasures.data.services.automation_failure_hooks.CriticalAutomationFailure`, which
names the automation, its asset, the run, the stage it failed in and the error it failed on.

Register one from a plugin, next to its ``__automation_types__``:

.. code-block:: python

    def page_the_engineer_on_duty(failure):
        pager.trigger(severity="critical", summary=failure.summary)

    __automation_failure_hooks__ = [page_the_engineer_on_duty]

Or name it by dotted path in your server settings, if you would rather not write a plugin:

.. code-block:: python

    FLEXMEASURES_CRITICAL_AUTOMATION_FAILURE_HOOKS = ["my_company.ops.page_the_engineer_on_duty"]

The hooks are called when FlexMeasures has stopped trying: when a job of the run failed on a
worker, which is not retried, or when the run's last dispatch attempt has been spent (see
:ref:`automation_runs`), so that a dispatch which the next retry would have fixed does not page
anybody. A run notifies once, however many of its jobs fail, which is recorded on the run itself,
so a second dispatcher or worker does not page again.

Hooks run inside the dispatcher or worker that recorded the failure, straight after it was
recorded. Keep them quick, and put anything slow on a queue of your own: a hook that raises is
logged and skipped, and never fails the run it was told about, which has failed already.


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

Each scheduled run a runner picks up is recorded durably, so a queueing attempt which fails can be retried without duplicating the jobs it already created.
See :ref:`automation_runs`.

The jobs record how they were created, which is shown on the asset's status page (UI), where recent jobs are listed.

.. _automation_runs:

Runs and retries
----------------

Every scheduled run a runner picks up gets a record in the database, which outlives the jobs it creates (jobs in Redis expire).
These records expire, too, though much later: once an hour, the runner deletes the runs that are older than their automation type's time-to-live (by default 14 days for ingestion, 90 days for scheduling and 60 days for other types).
It always keeps the latest run of each automation, and a failure that monitoring has not reported yet.
See :ref:`automation_dblogs_ttl`.
The runner claims the run before doing any work, and the database allows only one record per automation, scheduled time and revision, so two runners started in the same minute cannot both execute it.
A claim comes with a lease: while one runner holds a live lease on a run, no other runner touches it, and once that lease expires the run is up for grabs again, which is how a runner that died mid-queueing hands its work over.

Before queueing anything, the runner writes down the plan for the run: the parameters it will use and the individual jobs it intends to create, each with its own logical name and a job ID derived from the run.
This is what makes a retry safe.
A run which failed before queueing anything is dispatched again in full.
A run which queued only some of its jobs resumes from the same plan, recognizes the jobs already in Redis by their IDs, and queues only the ones still missing, so a retry never duplicates work, and never silently drops it either.
Because the plan is stored, a retry hours later still uses the parameters the run was planned with, even if the automation has been edited since.
A forecast start the automation left to the run time is resolved on the first attempt and stored with those parameters, so a run resumed hours later still forecasts the window its first attempt started on.
The same goes for the time up to which a forecast uses recorded data, so a resumed run forecasts with the data its first attempt had, not with data recorded since.

A dispatch which fails is attempted again, each time after a longer wait, and stops being attempted after five attempts.
A dispatch that keeps failing usually fails for a reason no retry fixes, such as a sensor that was deleted,
and the run's record says what went wrong on each attempt.

A forecast run and a schedule run are both retried this way.
Each names its jobs after the run it belongs to, rather than letting them take a fresh identity on every dispatch,
which is what lets a second attempt tell the jobs the first one queued from the ones it still owes:
a schedule run that queued two of its three devices queues the third, and schedules no device twice.
A schedule start the automation left to the run time is resolved on the first attempt and stored with the run's parameters,
so the devices a resumed run still owes are scheduled for the same window as the devices it already queued.

A run also records each job it created, and how that job ended, which is what its *execution* state describes.
This holds for every type of automation: a schedule run records its scheduling job (or, for a sequential schedule, each device job and the job wrapping them up),
a report run its reporting job, and a plugin run the job its plugin queued.
A run which queued no jobs, such as a report run with nothing new to report on, has succeeded.
A job which a schedule queues to fall back on a simpler scheduler is not one of the run's jobs, so a run whose schedule fell back has failed, with the error that made it fall back.

A run tracks two things separately: how far its *dispatch* got (``pending``, ``claimed``, ``partially_queued``, ``queued`` or ``failed``), and how its *execution* by the workers ended (``pending``, ``running``, ``succeeded``, ``failed`` or ``canceled``).
Each attempt to dispatch a run is recorded too, with the runner which made it, what it queued, and why it failed if it did.
This is what an operator needs to tell a run which failed before queueing anything, one which queued half its work, and one which queued everything but then failed while computing, apart from each other.

Editing an automation's cron string, timezone, parameters or data generator config, or reactivating it, counts up its revision.
Runs from before and after the change therefore stay distinct, even when they fall on the same scheduled UTC time.

.. _monitoring_automations:

Monitoring automation runs
--------------------------

As a host, you can have FlexMeasures email you a digest of the automation runs that failed, by running ``flexmeasures monitor automations`` regularly, for instance every hour:

.. code-block:: bash

    0 * * * * flexmeasures monitor automations

A run is reported when its execution failed, when it has been executing for longer than six hours, or when its dispatch failed and will not be attempted again.
A forecast run therefore counts once its five dispatch attempts are used up, and a run of any other type after its first failed attempt.
The six hours are set by :ref:`monitor_automations_stuck_after`, and ``--stuck-after-minutes`` overrides that setting.

Each run is reported once, so if one monitoring run is missed, the next one still reports what failed in the meantime.
Repeated failures of an automation are collapsed into one entry, saying how often it failed, when it first and last did, and with which error.
No email is sent when nothing failed.

Every automation is monitored, unless it opts out, for instance an experiment whose failures nobody needs to hear about.
Untick *Monitored* on the Automations page, create it with ``flexmeasures add automation --unmonitored``, switch it with ``flexmeasures edit automation --monitored/--unmonitored``, or send ``"monitored": false`` to the API.
Its runs are then left out of every digest.
They are not marked as reported, though, so once the automation is monitored again, the next digest reports the runs that failed in the meantime,
saying how many of them failed while it was not monitored, and when monitoring was switched back on.
Only the host's admins and the account-admins of the asset's organisation may switch monitoring off or on, as it decides what the recipients of the digest hear about.
Switching it off only keeps the automation out of these digests; the automation runs as before.

The digest goes to :ref:`default_monitoring_mail_recipients`, or to whoever you name with ``--recipient`` (a user ID or an email address, as often as needed).
The command stays out of ``flexmeasures jobs run-automations``, so that a problem with monitoring, such as an unreachable mail server, never holds up the automations themselves.

The people responsible for the assets can receive a digest of their own, once you add ``--notify-users`` to the command.
Each user with the ``account-admin`` role in an asset's organisation, and each user with the ``consultant`` role in its consultancy organisation, then receives one email per monitoring run,
listing only the automations they can see.
Inactive users and users without an email address are skipped.
Automations on public assets belong to no organisation, so they only appear in your digest, which keeps listing every failed run.
A run counts as reported once your digest is sent, so a user digest that cannot be delivered is logged, and not sent again.

Running one automation on demand
--------------------------------

Besides its recurring runs, a single automation can be run now, once.
This is useful to try out a new automation, to re-run one after fixing what made it fail, or to refresh its results after late input data arrived.

.. code-block:: bash

    flexmeasures jobs run-automation --automation 4

The same is available in the API, as `[POST] /assets/(id)/automations/(automation-id)/trigger <../api/v3_0.html#post--api-v3_0-assets-id-automations-automation-id-trigger>`_, and in the UI, as *Run now* in the automation's *Actions* menu on the asset's *Automations* page.
That menu also lets you edit, copy, deactivate (or activate) and delete the automation.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_automation_actions.png
    :align: center
..    :scale: 40%

|

The automation runs with the parameters it was created with, and the jobs it queues are recorded as its jobs, just like the jobs of a recurring run.
An on-demand run does not affect the automation's recurrence: its cursor (see :ref:`automation_cursor`) stays where it was, so the next recurring run still happens as scheduled, and a run missed while the runner was down is still caught up.
Inactive automations can be run this way, too, which is how you can try one out before activating it.

Unlike a recurring run, an on-demand run is not protected against being started twice: asking for two runs in a row queues two runs.

Viewing automations
-------------------

Automations defined on an asset can be viewed on the asset's *Automations* page in the UI, and listed with the API endpoint `[GET] /assets/(id)/automations <../api/v3_0.html#get--api-v3_0-assets-id-automations>`_.
Automations are usually defined on a sub-asset, so the page lists what runs anywhere below the asset as well, naming the asset each automation belongs to.
Turn *Include automations of sub-assets* off to see only the automations defined on the asset itself; the choice is remembered for your next visit.
The API endpoint does the same, and takes ``include-child-assets=false`` to narrow the listing.
Either way, only the assets you may read are included.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_asset_automations.png
    :align: center
..    :scale: 40%

|

The page shows how far off each automation's next scheduled run is, such as "in 6 minutes" or "tomorrow" (excluding any pending catch-up run).
Hovering it gives the exact time, read on the automation's own timezone, together with the recurrence it follows.
Created At reads on that same clock.
The page brings itself up to date once a minute, so runs and job counts appear without reloading; it holds off while the tab is in the background, or while a panel or menu is open.

An automation's *Info* panel shows the sensors it reads from and writes to, linking to each sensor's page, and the data source it records under, together with the configuration that data source was created with.
It also summarizes the automation's recent runs and their outcomes (see :ref:`automation_runs`).
Conversely, a sensor's page lists the automations that write data to it.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_automation_info.png
    :align: center
..    :scale: 40%

|

Each row's *Actions* menu also offers *Copy*, which opens the creation form with that automation's type, recurrence, timezone and parameters filled in, and its data source already selected.
It is a starting point for a variation on an existing automation, such as the same forecast on a different recurrence, rather than a command of its own: nothing is created until you submit the form, and you can change anything in it first.
The copy is created inactive, so that it does not start running while you are still working on it, and it is named after the original with a ``(copy)`` suffix.

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
