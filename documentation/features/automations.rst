.. _automations:

Automations
============

Hosts and users often want the three main FlexMeasures features — :ref:`forecasting`, :ref:`scheduling` and :ref:`reporting` — to run on a recurring basis, across larger numbers of sites.
*Automations* make that a first-class concept: an automation is a recurring task defined on an asset, and each time it runs, it queues jobs.

An automation consists of:

- a **type**: ``forecasts``, ``schedules`` or ``reports``;
- a **recurrence**: a cron string (e.g. ``"0 6 * * *"`` for daily at 6 AM), interpreted in the ``FLEXMEASURES_TIMEZONE``;
- a **data generator** (for forecasts and reports): the forecaster or reporter class and its configuration, stored on a data source.
  The data source stays the same across runs, so all results the automation produces attribute to one steady source;
- **parameters**: what to compute on each run, validated by the same schema the CLI and API use for one-off runs.
  Timing parameters are resolved freshly on each run, so a recurring automation always computes fresh periods
  (see the type-specific sections below for the exact rules);
- an **activation status**: only active automations run.

Managing automations
--------------------

Automations can be managed in three ways:

- **CLI**: ``flexmeasures add automation``, ``flexmeasures edit automation`` (name, cron string, activation status) and ``flexmeasures delete automation``.
- **API**: list and inspect with ``[GET] /assets/(id)/automations`` and ``[GET] /assets/(id)/automations/(automation_id)``;
  create, update and delete with ``[POST|PATCH|DELETE]`` on the same paths (see the `API documentation <../api/v3_0.html>`_).
- **UI**: each asset has an *Automations* page (in the breadcrumbs dropdown), with a tab per automation type.
  It lists each automation's recurrence and recent job counts, and lets you create, (de)activate and delete automations.

Creating, updating and deleting automations requires account admin or consultant rights, and is recorded in the asset's audit log.

Running automations
--------------------

An automation is due whenever its cron string matches the current minute. To actually run due automations, let a cron job execute the following command once per minute:

.. code-block:: bash

    * * * * * flexmeasures jobs run-automations

Each due automation then queues its jobs — so make sure workers are processing the relevant queues (``forecasting``, ``scheduling`` and/or ``reporting``, see :ref:`redis-queue`).
A Redis-based guard prevents queueing jobs twice if the command happens to run more than once within the same minute.

Jobs record how they were created (via the CLI, the API or an automation), which is shown in the *Created Via* column
of the jobs table on the asset's status page, where recent jobs are listed.

Automating each feature
-----------------------

The parameters stored on an automation follow the same schemas as one-off CLI/API calls, with type-specific rules for resolving timing on each run:

- :ref:`automating_forecasts` — forecast parameters; the forecast start defaults to the run time.
- :ref:`automating_schedules` — a schedule trigger message; omit ``start`` to schedule from the run time.
- :ref:`automating_reports` — report parameters; use ``start-offset``/``end-offset`` (Pandas offsets) for a rolling window,
  or omit timing fields to report on the period since the automation's actual last run.
