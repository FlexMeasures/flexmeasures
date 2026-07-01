.. _scheduling:

Scheduling 
===========

Scheduling is the main value-drive of FlexMeasures. We have two major types of schedulers built-in, for storage devices (usually batteries or hot water storage) and processes (usually in industry).

FlexMeasures computes schedules for energy systems that consist of multiple devices that consume and/or produce electricity.
We model a device as an asset with a power sensor, and compute schedules only for flexible devices, while taking into account inflexible devices.

.. contents::
    :local:
    :depth: 2


.. _describing_flexibility:

Describing flexibility
----------------------

To compute a schedule, FlexMeasures first needs to assess the flexibility state of the system.
This is described by:

- :ref:`The flex-context <flex_context>` ― information about the system as a whole, in order to assess the value of activating flexibility.
- :ref:`Flex-models <flex_models_and_schedulers>`  ― information about the state and possible actions of the flexible device. We will discuss these per scheduled device type.

This information goes beyond the usual time series recorded by an asset's sensors. It can be sent to FlexMeasures through the API when triggering schedule computation.
Also, this information can be persisted on the FlexMeasures data model (in the db), and is editable through the UI (actually, that is design work in progress, currently possible with the flex context).

.. note:: You can also specify the **scheduling resolution** to control how often setpoints can change in the schedule. See :ref:`scheduling_resolution` for details on when and how to use custom resolutions.

Let's dive into the details ― what can you tell FlexMeasures about your optimization problem?


.. _flex_context:

The flex-context
-----------------

The ``flex-context`` is independent of the type of flexible device that is optimized, or which scheduler is used.
With the flexibility context, we aim to describe the system in which the flexible assets operate, such as its physical and contractual limitations.

Fields can have fixed values, but some fields can also point to sensors, so they will always represent the dynamics of the asset's environment (as long as that sensor has current data).
The full list of flex-context fields follows below.
For more details on the possible formats for field values, see :ref:`variable_quantities`.

Where should you set these fields?
Within requests to the API or by editing the relevant asset in the UI.
If they are not sent in via the API (one of the endpoints triggering schedule computation), the scheduler will look them up on the `flex-context` field of the asset.
And if the asset belongs to a larger system (a hierarchy of assets), the scheduler will also search if parent assets have them set.



.. list-table::
   :header-rows: 1
   :widths: 20 25 90

   * - Field
     - Example value
     - Description
   * - ``inflexible-device-sensors``
     - |INFLEXIBLE_DEVICE_SENSORS.example|
     - .. include:: ../_autodoc/INFLEXIBLE_DEVICE_SENSORS.rst
   * - ``aggregate-power``
     - |AGGREGATE_POWER.example|
     - .. include:: ../_autodoc/AGGREGATE_POWER.rst
   * - ``consumption-price``
     - |CONSUMPTION_PRICE.example|
     - .. include:: ../_autodoc/CONSUMPTION_PRICE.rst
   * - ``production-price``
     - |PRODUCTION_PRICE.example|
     - .. include:: ../_autodoc/PRODUCTION_PRICE.rst
   * - ``site-power-capacity``
     - |SITE_POWER_CAPACITY.example|
     - .. include:: ../_autodoc/SITE_POWER_CAPACITY.rst
   * - ``site-consumption-capacity``
     - |SITE_CONSUMPTION_CAPACITY.example|
     - .. include:: ../_autodoc/SITE_CONSUMPTION_CAPACITY.rst
   * - ``site-production-capacity``
     - |SITE_PRODUCTION_CAPACITY.example|
     - .. include:: ../_autodoc/SITE_PRODUCTION_CAPACITY.rst
   * - ``site-peak-consumption``
     - |SITE_PEAK_CONSUMPTION.example|
     - .. include:: ../_autodoc/SITE_PEAK_CONSUMPTION.rst
   * - ``relax-constraints``
     - |RELAX_CONSTRAINTS.example|
     - .. include:: ../_autodoc/RELAX_CONSTRAINTS.rst
   * - ``site-consumption-breach-price``
     - |SITE_CONSUMPTION_BREACH_PRICE.example|
     - .. include:: ../_autodoc/SITE_CONSUMPTION_BREACH_PRICE.rst
   * - ``site-production-breach-price``
     - |SITE_PRODUCTION_BREACH_PRICE.example|
     - .. include:: ../_autodoc/SITE_PRODUCTION_BREACH_PRICE.rst
   * - ``site-peak-consumption-price``
     - |SITE_PEAK_CONSUMPTION_PRICE.example|
     - .. include:: ../_autodoc/SITE_PEAK_CONSUMPTION_PRICE.rst
   * - ``site-peak-production``
     - |SITE_PEAK_PRODUCTION.example|
     - .. include:: ../_autodoc/SITE_PEAK_PRODUCTION.rst
   * - ``site-peak-production-price``
     - |SITE_PEAK_PRODUCTION_PRICE.example|
     - .. include:: ../_autodoc/SITE_PEAK_PRODUCTION_PRICE.rst
   * - ``soc-minima-breach-price``
     - |SOC_MINIMA_BREACH_PRICE.example|
     - .. include:: ../_autodoc/SOC_MINIMA_BREACH_PRICE.rst
   * - ``soc-maxima-breach-price``
     - |SOC_MAXIMA_BREACH_PRICE.example|
     - .. include:: ../_autodoc/SOC_MAXIMA_BREACH_PRICE.rst
   * - ``consumption-breach-price``
     - |CONSUMPTION_BREACH_PRICE.example|
     - .. include:: ../_autodoc/CONSUMPTION_BREACH_PRICE.rst
   * - ``production-breach-price``
     - |PRODUCTION_BREACH_PRICE.example|
     - .. include:: ../_autodoc/PRODUCTION_BREACH_PRICE.rst
   * - ``commitments``
     - |COMMITMENTS.example|
     - .. include:: ../_autodoc/COMMITMENTS.rst

.. [#old_consumption_price_field] This field replaced the ``consumption-price-sensor`` field, which only accepted an integer (sensor ID).

.. [#old_production_price_field] This field replaced the ``production-price-sensor`` field, which only accepted an integer (sensor ID).

.. [#asymmetric] ``site-consumption-capacity`` and ``site-production-capacity`` allow defining asymmetric contracted transport capacities for each direction (i.e. production and consumption).

.. [#minimum_capacity_overlap] In case this capacity field defines partially overlapping time periods, the minimum value is selected. See :ref:`variable_quantities`.

.. [#consumption] Example: with a connection capacity (``site-power-capacity``) of 1 MVA (apparent power) and a consumption capacity (``site-consumption-capacity``) of 800 kW (active power), the scheduler will make sure that the grid outflow doesn't exceed 800 kW.

.. [#penalty_field] Prices must share the same currency. Negative prices are not allowed (penalties only).

.. [#production] Example: with a connection capacity (``site-power-capacity``) of 1 MVA (apparent power) and a production capacity (``site-production-capacity``) of 400 kW (active power), the scheduler will make sure that the grid inflow doesn't exceed 400 kW.

.. [#breach_field] Breach prices are applied both to (the height of) the highest breach in the planning window and to (the area of) each breach that occurs.
                   That means both high breaches and long breaches are penalized.
                   For example, a :abbr:`SoC (state of charge)` breach price of 120 EUR/kWh is applied as a breach price of 120 EUR/kWh on the height of the highest breach, and as a breach price of 120 EUR/kWh/h on the area (kWh*h) of each breach.
                   For a 5-minute resolution sensor, this would amount to applying a SoC breach price of 10 EUR/kWh for breaches measured every 5 minutes (in addition to the 120 EUR/kWh applied to the highest breach only).

.. note:: If no (symmetric, consumption and production) site capacity is defined (also not as defaults), the scheduler will not enforce any bound on the site power.
          The flexible device can still have its own power limit defined in its flex-model.


.. _flex_models_and_schedulers:

The flex-models & corresponding schedulers
-------------------------------------------

FlexMeasures comes with a storage scheduler and a process scheduler, which work with flex models for storages and loads, respectively.

The storage scheduler is suitable for batteries and :abbr:`EV (electric vehicle)` chargers, and is automatically selected when scheduling an asset with one of the following asset types: ``"battery"``, ``"one-way_evse"`` and ``"two-way_evse"``.

The process scheduler is suitable for shiftable, breakable and inflexible loads, and is automatically selected for asset types ``"process"`` and ``"load"``.


We describe the respective flex models below.

These fields can be configured in the UI editor on the asset properties page or sent through the API (one of the endpoints to trigger schedule computation, or using the FlexMeasures client) or through the CLI (the command to add schedules).


Storage
^^^^^^^^

For *storage* devices, the FlexMeasures scheduler deals with the state of charge (SoC) for an optimal outcome.
You can do a lot with this ― examples for storage devices are:

- batteries
- :abbr:`EV (electric vehicle)` batteries connected to charge points
- hot water storage ("heat batteries", where the SoC relates to the water temperature)
- pumped hydro storage (SoC is the water level)
- water basins (here, SoC is supposed to be low, as water is being pumped out)
- buffers of energy-intensive chemicals that are needed in other industry processes


The ``flex-model`` for storage devices describes to the scheduler what the flexible asset's state is,
and what constraints or preferences should be taken into account.

The full list of flex-model fields for the storage scheduler follows below.
For more details on the possible formats for field values, see :ref:`variable_quantities`.

.. list-table::
   :header-rows: 1
   :widths: 20 40 80

   * - Field
     - Example value
     - Description
   * - ``consumption``
     - |CONSUMPTION.example|
     - .. include:: ../_autodoc/CONSUMPTION.rst
   * - ``production``
     - |PRODUCTION.example|
     - .. include:: ../_autodoc/PRODUCTION.rst
   * - ``state-of-charge``
     - |STATE_OF_CHARGE.example|
     - .. include:: ../_autodoc/STATE_OF_CHARGE.rst
   * - ``soc-at-start``
     - |SOC_AT_START.example|
     - .. include:: ../_autodoc/SOC_AT_START.rst
   * - ``soc-unit``
     - |SOC_UNIT.example|
     - .. include:: ../_autodoc/SOC_UNIT.rst
   * - ``soc-min``
     - |SOC_MIN.example|
     - .. include:: ../_autodoc/SOC_MIN.rst
   * - ``soc-max``
     - |SOC_MAX.example|
     - .. include:: ../_autodoc/SOC_MAX.rst
   * - ``soc-minima``
     - |SOC_MINIMA.example|
     - .. include:: ../_autodoc/SOC_MINIMA.rst
   * - ``soc-maxima``
     - |SOC_MAXIMA.example|
     - .. include:: ../_autodoc/SOC_MAXIMA.rst
   * - ``soc-targets``
     - |SOC_TARGETS.example|
     - .. include:: ../_autodoc/SOC_TARGETS.rst
   * - ``soc-gain``
     - |SOC_GAIN.example|
     - .. include:: ../_autodoc/SOC_GAIN.rst
   * - ``soc-usage``
     - |SOC_USAGE.example|
     - .. include:: ../_autodoc/SOC_USAGE.rst
   * - ``roundtrip-efficiency``
     - |ROUNDTRIP_EFFICIENCY.example|
     - .. include:: ../_autodoc/ROUNDTRIP_EFFICIENCY.rst
   * - ``charging-efficiency``
     - |CHARGING_EFFICIENCY.example|
     - .. include:: ../_autodoc/CHARGING_EFFICIENCY.rst
   * - ``discharging-efficiency``
     - |DISCHARGING_EFFICIENCY.example|
     - .. include:: ../_autodoc/DISCHARGING_EFFICIENCY.rst
   * - ``storage-efficiency``
     - |STORAGE_EFFICIENCY.example|
     - .. include:: ../_autodoc/STORAGE_EFFICIENCY.rst
   * - ``prefer-charging-sooner``
     - |PREFER_CHARGING_SOONER.example|
     - .. include:: ../_autodoc/PREFER_CHARGING_SOONER.rst
   * - ``prefer-curtailing-later``
     - |PREFER_CURTAILING_LATER.example|
     - .. include:: ../_autodoc/PREFER_CURTAILING_LATER.rst
   * - ``power-capacity``
     - |POWER_CAPACITY.example|
     - .. include:: ../_autodoc/POWER_CAPACITY.rst
   * - ``consumption-capacity``
     - |CONSUMPTION_CAPACITY.example|
     - .. include:: ../_autodoc/CONSUMPTION_CAPACITY.rst
   * - ``production-capacity``
     - |PRODUCTION_CAPACITY.example| (only consumption)
     - .. include:: ../_autodoc/PRODUCTION_CAPACITY.rst

.. [#quantity_field] Can only be set as a fixed quantity.

.. [#maximum_overlap] In case this field defines partially overlapping time periods, the maximum value is selected. See :ref:`variable_quantities`.

.. [#minimum_overlap] In case this field defines partially overlapping time periods, the minimum value is selected. See :ref:`variable_quantities`.

For more details on the possible formats for field values, see :ref:`variable_quantities`.

Usually, not the whole flexibility model is needed.
FlexMeasures can infer missing values in the flex model, and even get them (as default) from the sensor's attributes.

You can add new storage schedules with the CLI command ``flexmeasures add schedule``.

If you model devices that *buffer* energy (e.g. thermal energy storage systems connected to heat pumps), we can use the same flexibility parameters described above for storage devices.
However, here are some tips to model a buffer correctly:

   - Describe the thermal energy content in kWh or MWh.
   - Set ``soc-minima`` to the accumulative usage forecast.
   - Set ``charging-efficiency`` to the sensor describing the :abbr:`COP (coefficient of performance)` values.
   - Set ``storage-efficiency`` to a value below 100% to model (heat) loss.

What happens if the flex model describes an infeasible problem for the storage scheduler? Excellent question!
It is highly important for a robust operation that these situations still lead to a somewhat good outcome.
From our practical experience, we derived a ``StorageFallbackScheduler``.
It simplifies an infeasible situation by just starting to charge, discharge, or do neither,
depending on the first target state of charge and the capabilities of the asset.

Of course, we also log a failure in the scheduling job, so it's important to take note of these failures. Often, mis-configured flex models are the reason.

For a hands-on tutorial on using some of the storage flex-model fields, head over to :ref:`tut_v2g` use case and `the API documentation for triggering schedules <../api/v3_0.html#post--api-v3_0-assets-id-schedules-trigger>`_.

Finally, are you interested in the linear programming details behind the storage scheduler?
Then head over to :ref:`storage_device_scheduler`!
You can also review the current flex-model for storage in the code, at ``flexmeasures.data.schemas.scheduling.storage.StorageFlexModelSchema``.


Shiftable loads (processes)
^^^^^^^^^^^^^^^^^^^^^^^^^^

For *processes* that can be shifted or interrupted, but have to happen at a constant rate (of consumption), FlexMeasures provides the ``ProcessScheduler``.
Some examples from practice (usually industry) could be:

- A centrifuge's daily work of combing through sludge water. Depends on amount of sludge present.
- Production processes with a target amount of output until the end of the current shift. The target usually comes out of production planning.
- Application of coating under hot temperature, with fixed number of times it needs to happen before some deadline.   
   
.. list-table::
   :header-rows: 1
   :widths: 20 25 90

   * - Field
     - Example value
     - Description 
   * - ``power``
     - ``"15kW"``
     - Nominal power of the load.
   * - ``duration``
     - ``"PT4H"``
     - Time that the load needs to lasts.
   * - ``optimization_direction``
     - ``"MAX"``
     - Objective of the scheduler, to maximize (``"MAX"``) or minimize (``"MIN"``).
   * - ``time_restrictions``
     - ``[{"start": "2015-01-02T08:00:00+01:00", "duration": "PT2H"}]`` 
     - Time periods in which the load cannot be scheduled to run.
   * - ``process_type``
     - ``"INFLEXIBLE"``, ``"SHIFTABLE"`` or ``"BREAKABLE"``
     - Is the load inflexible and should it run as soon as possible? Or can the process's start time be shifted? Or can it even be broken up into smaller segments?

You can review the current flex-model for processes in the code, at ``flexmeasures.data.schemas.scheduling.process.ProcessSchedulerFlexModelSchema``.

You can add new shiftable-process schedules with the CLI command ``flexmeasures add schedule``. Make sure to use the ``--scheduler ProcessScheduler`` option to use the in-built process scheduler.

.. note:: Currently, the ``ProcessScheduler`` uses only the ``consumption-price`` field of the flex-context, so it ignores any site capacities and inflexible devices.


The schedule
------------

A schedule produced by FlexMeasures is a series of power values for each flexible device (represented by its power sensor), covering the scheduling window at the scheduling resolution.

For detailed constraint analysis (unresolved constraints and margins), use the ``GET /api/v3_0/jobs/<uuid>`` endpoint, which provides structured information about constraints organized by asset. See the :ref:`scheduling_constraint_results` section below for details.


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

**When no constraints are defined:**

If ``unresolved`` and ``resolved`` are both empty, no state-of-charge constraints were set.

.. note:: Hard constraints (``soc-targets``) are never reported in results because the scheduler enforces them strictly by definition.
          If a hard constraint cannot be met, the entire scheduling job will fail, not produce results with violations.

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


Checking the status via the API
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
