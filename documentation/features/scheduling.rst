.. _scheduling:

Scheduling
===========

Scheduling is the main value-drive of FlexMeasures. We have two major types of schedulers built-in, for storage devices (usually batteries or hot water storage) and processes (usually in industry).

FlexMeasures computes schedules for energy systems that consist of multiple devices that consume and/or produce a commodity (e.g. electricity or gas).
We model a device as an asset with a consumption/production sensor recording power values, and compute schedules only for flexible devices, while taking into account inflexible devices.

.. contents::
    :local:
    :depth: 1

|


Describing the optimization problem
-----------------------------------

Before FlexMeasures can compute a schedule, it needs a description of the
available flexibility and its context. The ``flex-context`` describes the
system-wide situation and objective, while each ``flex-model`` describes one
flexible device. For example, this configuration tells FlexMeasures which
sensor holds the electricity price and gives the current state and operating
limits of a battery:

.. code-block:: json

   {
       "flex-context": {
           "consumption-price": {"sensor": 7}
       },
       "flex-model": [
           {
               "sensor": 8,
               "soc-at-start": "50 kWh",
               "soc-min": "10 kWh",
               "soc-max": "100 kWh",
               "power-capacity": "50 kW"
           }
       ]
   }

Here, sensor 8 is the power sensor on the battery asset and identifies the
device to be scheduled. Sensor 7 supplies the electricity-price series against
which the battery is optimized.

More than one device can be scheduled in the same optimization: add one
flex-model entry per flexible device. See
:ref:`tut_toy_schedule_multiasset_curtailment` for a tutorial that jointly
schedules a battery and curtailable PV.

Configurations that change rarely can be stored on assets. A scheduling
request can add or override the parts that are specific to that run. See
:ref:`flexibility_configuration` for the complete flex-context and flex-model
reference.


Triggering a schedule computation
---------------------------------

To start a computation, select the asset whose energy system should be
optimized and provide a scheduling window. If the configuration above is
stored in the asset tree, an API request for a four-hour schedule can be this
small:

.. code-block:: http

   POST /api/v3_0/assets/6/schedules/trigger

.. code-block:: json

   {
       "start": "2026-08-10T07:00:00+02:00",
       "duration": "PT4H",
       "resolution": "PT1H"
   }

Calling this endpoint makes asset 6 the root of the optimization. FlexMeasures
collects stored flex-models from asset 6 and its descendants, and collects
flex-context fields from asset 6 upwards through its ancestors. Nearer context
values take precedence. Only devices represented by the collected flex-models
are scheduled—not every descendant with a power sensor automatically—and they
are considered together in one optimization problem.

Alternatively, include ``flex-context`` and ``flex-model`` in this body to
supply or override them for this computation. The endpoint returns
``202 Accepted`` with a ``job`` UUID. Poll
``GET /api/v3_0/jobs/<uuid>`` until the job finishes, then retrieve each
device's schedule from ``GET /api/v3_0/sensors/<id>/schedules/<uuid>``. The same
workflow is available through the CLI and FlexMeasures Client. See
:ref:`tut_toy_schedule` for a short hands-on example and the
`asset scheduling endpoint <../api/v3_0.html#post--api-v3_0-assets-id-schedules-trigger>`_
for all request fields.


The schedule
------------

A schedule produced by FlexMeasures is a series of power setpoints for each
flexible device, represented by its power sensor. For example, the values
``[0.5, 1.0, 1.5, 0.0]`` in ``kW`` describe four consecutive setpoints: the
battery first charges gently, increases its charging power, and then becomes
idle. The result also states the series start and duration, so a controller can
apply each value at the scheduling resolution.

After the scheduling job has finished, retrieving this simplified schedule
through ``GET /api/v3_0/sensors/8/schedules/<uuid>`` returns JSON like this:

.. code-block:: json

   {
       "scheduler_info": {
           "scheduler": "StorageScheduler"
       },
       "values": [0.5, 1.0, 1.5, 0.0],
       "start": "2026-08-10T07:00:00+02:00",
       "duration": "PT4H",
       "unit": "kW",
       "status": "PROCESSED",
       "message": "StorageScheduler was used."
   }

Together with the one-hour resolution requested above, this response describes
four hourly events: 07:00–08:00, 08:00–09:00, 09:00–10:00, and 10:00–11:00.
The schedule therefore covers the four-hour period from 07:00 to 11:00.

Schedules can be inspected alongside prices, forecasts, measurements, and
state of charge in the FlexMeasures UI:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-charging.png
   :align: center

*A battery schedule in the sensor data view.*

For detailed constraint analysis (unresolved constraints and margins), use the ``GET /api/v3_0/jobs/<uuid>`` endpoint, which provides structured information about constraints organized by asset. See the :ref:`scheduling_constraint_results` section below for details.


Inspecting schedules
-----------------------

It can be crucial to inspect how your scheduling job is doing.
Here are some ways to do that:

Errors
^^^^^^^

FlexMeasures will validate flex-config and asset & sensor IDs before starting the job,
and let you know (in the console or API response) what went wrong.


Checking the status via the API
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There is an API endpoint specifically for checking status, result and configuration info for jobs:
``GET /api/v3_0/jobs/{uuid}`` returns JSON with the job status, result, queue and function metadata, timestamps, and exception traceback information for failed jobs.
For scheduling jobs specifically, this includes the constraint analysis described in :ref:`scheduling_constraint_results` below.


Checking the status via the CLI
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There is also a CLI command, which basically mirrors what the API endpoint does (see above). Here is an example call:

.. code-block:: bash

    flexmeasures jobs inspect-job --job 40ac6f2e-690d-4865-8203-429e54179112


The asset status page: listing jobs and more info
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Each asset has a status page where you can find recent jobs which were run in the context of this asset.
Clicking the "Info" button will give you a lot more insights into the jobs' configuration than the above methods.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_status_page_job_info.png
    :align: center
..    :scale: 40%

|


The RQ-dashboard: complete overview
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Internally, jobs are queued with the python-rq library. For this, a job dashboard is available, which
users with the ``admin`` role can access via the menu. This gives a complete overview over all jobs
running in FlexMeasures.

You find your jobs via the queues, see screenshot below.
Clicking a job gives you more information, similar to the status page.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_rq_dashboard.png
    :align: center
..    :scale: 40%

|


.. _scheduling_constraint_results:

Accessing constraint results
-----------------------------

When a schedule is computed for a device with state-of-charge constraints, FlexMeasures analyzes whether the constraints can be met.

Use the **jobs endpoint** (``GET /api/v3_0/jobs/<uuid>``) to retrieve detailed constraint analysis for all assets involved in the scheduling job, organized by asset ID.
This endpoint is useful when you want to inspect constraint violations without retrieving the full schedule.

Multi-asset scheduling workflow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Consider a site (asset ID 123) with four assets, each with a power sensor:

- **Sensors 1 & 2**: Inflexible devices (e.g. PV panel and building load)
- **Sensors 3 & 4**: Flexible devices (e.g. a battery and an EV charger),
  each with a state-of-charge sensor (sensors 5 and 6, respectively)

The scheduling workflow looks like this:

1. **Trigger the schedule** for site asset 123 via
   ``POST /api/v3_0/assets/123/schedules/trigger``.
   The endpoint returns a job UUID, e.g. ``"5d28df1b-9f16-4177-ae43-6e750d80fad3"``.

2. **Retrieve the scheduled power series** for the flexible devices once scheduling is done,
   via ``GET /api/v3_0/sensors/3/schedules/<uuid>`` and ``GET /api/v3_0/sensors/4/schedules/<uuid>``.
   Each response contains the power setpoints for that device:

   .. code-block:: json

       {
           "values": [0.5, 1.0, 1.5, 0.0],
           "start": "2024-01-15T08:00:00+00:00",
           "duration": "PT4H",
           "unit": "kW"
       }

3. **Retrieve constraint analysis** for all flexible assets via ``GET /api/v3_0/jobs/<uuid>``.
   The ``result`` field in the response shows whether the state-of-charge targets for sensors 5 and 6 could be met, and by how much.
   For a finished ``StorageScheduler`` job, ``result`` is always an object with ``unresolved`` and ``resolved`` constraint analysis (as shown below);
   both arrays are simply empty when the flex model defines no ``soc-minima``/``soc-maxima``, or when a scheduler other than ``StorageScheduler`` was used.

The constraint results distinguish between:

- Constraints that were **unresolved**: Soft constraints that could not be satisfied during optimization, with the shortfall or excess reported as their **violation**.
- Constraints that were **resolved**: Soft constraints that were satisfied, with the headroom remaining reported as their **margin**.

For each device, the ``soc-minima``/``soc-maxima`` value under ``unresolved`` or ``resolved`` is a **list** of entries — one per violated slot (unresolved) or per met slot with its margin (resolved), ordered chronologically.
By default, every violated or met slot is listed (this is not currently configurable via the API).
Each list entry includes:

- ``datetime``: ISO 8601 UTC timestamp of that slot.
- ``violation`` (unresolved only): Magnitude of the violation at that slot (shortage for minima, excess for maxima).
- ``margin`` (resolved only): Headroom remaining at that slot.

Both ``violation`` and ``margin`` are always reported as positive numbers (magnitudes), never negative — whether a violation is a shortage or an excess follows from the constraint type (``soc-minima`` vs. ``soc-maxima``), not from its sign.


Example: Constraint results from a battery scheduling job
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Suppose you schedule a battery device (asset ID 42) with the following constraints:

- **soc-minima**: Battery must stay above 60 kWh
- **soc-maxima**: Battery must not exceed 100 kWh

If the optimization cannot satisfy the minimum constraint at 10:30 UTC (falling short by 20 kWh) and again at 10:45 UTC (falling short by 15 kWh),
but does satisfy the maximum constraint with margins of 40 kWh at 11:00 UTC and 35 kWh at 12:00 UTC, the constraint results would show:

**Response via GET /api/v3_0/jobs/<uuid>:**

.. code-block:: json

    {
        "status": "FINISHED",
        "message": "Scheduling job finished.",
        "result": {
            "unresolved": [
                {
                    "asset": 42,
                    "soc-minima": [
                        {
                            "datetime": "2024-01-15T10:30:00+00:00",
                            "violation": "20.0 kWh"
                        },
                        {
                            "datetime": "2024-01-15T10:45:00+00:00",
                            "violation": "15.0 kWh"
                        }
                    ]
                }
            ],
            "resolved": [
                {
                    "asset": 42,
                    "soc-maxima": [
                        {
                            "datetime": "2024-01-15T11:00:00+00:00",
                            "margin": "40.0 kWh"
                        },
                        {
                            "datetime": "2024-01-15T12:00:00+00:00",
                            "margin": "35.0 kWh"
                        }
                    ]
                }
            ]
        }
    }


Interpreting constraint results for optimization decisions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**When constraints are all met:**

An empty ``unresolved`` array indicates successful optimization.
However, check the margins in ``resolved`` to understand how tight the constraints were:

- Large margins (e.g., 50 kWh) suggest the device has significant flexibility headroom.
- Small margins (e.g., 5 kWh) indicate the constraints were nearly violated.
- Zero margin would mean the device hit the exact constraint limit.

*Use case*: If you see very small margins, you may want to relax constraints or provide additional flexibility to create a more robust schedule.

**When constraints are unresolved:**

Unresolved constraints indicate the optimization problem was over-constrained. Common causes:

- Conflicting constraints, such as a high minimum on too short notice.
- Insufficient headroom within the grid capacity, caused by inflexible devices.

The ``violation`` values tell you how much shortfall exists:

- For ``soc-minima`` violations: The shortage in kWh. The device could not charge enough.
- For ``soc-maxima`` violations: The excess in kWh. The device could not discharge enough.

*Use case*: If a battery is reporting 20 kWh shortage for a planned trip, you may need to:

- Allow more time for charging.
- Install a larger battery.
- Reduce the minimum SoC requirement.
- Stretch the minimum SoC requirement over a longer time period (using the ``duration`` field) to continue charging in case the user plugs out later than expected.
- Warn the user about the shortfall.
- If the battery is in an EV, charge en-route.

**When no constraints are defined:**

If ``unresolved`` and ``resolved`` are both empty, no state-of-charge constraints were set.

.. note:: ``soc-targets`` are reported under ``unresolved`` only, and only while constraint relaxation is on.
          A target is a two-sided constraint, so its reported violation is the absolute deviation from the target, in either direction,
          and there is no headroom to report when a target is met.
          With relaxation off, a target that cannot be met makes the entire scheduling job fail instead of producing results with violations.

Work on other schedulers
---------------------------------------

We believe the two schedulers (and their flex-models) we describe here are covering a lot of use cases already.
Here are some thoughts on further innovation:

- Writing your own scheduler.
  You can always write your own scheduler (see :ref:`plugin_customization`).
  You then might want to add your own flex model, as well.
  FlexMeasures will let the scheduler decide which flexibility model is relevant and how it should be validated.
- We also aim to model situations with more than one flexible asset, and that have different types of flexibility (e.g. EV charging and smart heating in the same site).
  This is ongoing architecture design work, and therefore happens in development settings, until we are happy with the outcomes.
  Thoughts welcome :)
- Aggregating flexibility of a group of assets (e.g. a neighborhood) and optimizing its aggregated usage (e.g. for grid congestion support) is also an exciting direction for expansion.
