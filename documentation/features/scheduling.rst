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
     - ``[3,4]``
     - Power sensors that are relevant, but not flexible, such as a sensor recording rooftop solar power connected behind the main meter, whose production falls under the same contract as the flexible device(s) being scheduled.
       Their power demand cannot be adjusted but still matters for finding the best schedule for other devices. Must be a list of integers.
   * - ``consumption-price``
     - ``{"sensor": 5}``
       or
       ``"0.29 EUR/kWh"``
     - The price of consuming energy. Can be (a sensor recording) market prices, but also CO₂ intensity - whatever fits your optimization problem. (This field replaced the ``consumption-price-sensor`` field. [#old_sensor_field]_)
   * - ``production-price``
     - ``{"sensor": 6}``
       or
       ``"0.12 EUR/kWh"``
     - The price of producing energy.
       Can be (a sensor recording) market prices, but also CO₂ intensity - whatever fits your optimization problem, as long as the unit matches the ``consumption-price`` unit. (This field replaced the ``production-price-sensor`` field. [#old_sensor_field]_)
   * - ``site-power-capacity``
     - ``"45kVA"``
     - Maximum achievable power at the grid connection point, in either direction [#asymmetric]_.
       Becomes a hard constraint in the optimization problem, which is especially suitable for physical limitations. [#minimum_capacity_overlap]_
   * - ``site-consumption-capacity``
     - ``"45kW"``
     - Maximum consumption power at the grid connection point.
       If ``site-power-capacity`` is defined, the minimum between the ``site-power-capacity`` and ``site-consumption-capacity`` will be used. [#consumption]_
       If a ``site-consumption-breach-price`` is defined, the ``site-consumption-capacity`` becomes a soft constraint in the optimization problem.
       Otherwise, it becomes a hard constraint. [#minimum_capacity_overlap]_
   * - ``site-production-capacity``
     - ``"0kW"``
     - Maximum production power at the grid connection point.
       If ``site-power-capacity`` is defined, the minimum between the ``site-power-capacity`` and ``site-production-capacity`` will be used. [#production]_
       If a ``site-production-breach-price`` is defined, the ``site-production-capacity`` becomes a soft constraint in the optimization problem.
       Otherwise, it becomes a hard constraint. [#minimum_capacity_overlap]_
   * - ``site-peak-consumption``
     - ``{"sensor": 7}``
     - Current peak consumption.
       Costs from peaks below it are considered sunk costs. Default to 0 kW.
   * - ``relax-constraints``
     - ``True``
     - If True (default is ``False``), several constraints are relaxed by setting default breach prices within the optimization problem,
       leading to the default priority:

       1. Avoid breaching the site consumption/production capacity.
       2. Avoid not meeting SoC minima/maxima.
       3. Avoid breaching the desired device consumption/production capacity.

       We recommend to set this field to ``True`` to enable the default prices and associated priorities as defined by FlexMeasures.
       For tighter control over prices and priorities, the breach prices can also be set explicitly (see below).
   * - ``site-consumption-breach-price``
     - ``"1000 EUR/kW"``
     - The price of breaching the ``site-consumption-capacity``, useful to treat ``site-consumption-capacity`` as a soft constraint but still make the scheduler attempt to respect it.
       Can be (a sensor recording) contractual penalties, but also a theoretical penalty just to allow the scheduler to breach the consumption capacity, while influencing how badly breaches should be avoided. [#penalty_field]_ [#breach_field]_
   * - ``site-production-breach-price``
     - ``"1000 EUR/kW"``
     - The price of breaching the ``site-production-capacity``, useful to treat ``site-production-capacity`` as a soft constraint but still make the scheduler attempt to respect it.
       Can be (a sensor recording) contractual penalties, but also a theoretical penalty just to allow the scheduler to breach the production capacity, while influencing how badly breaches should be avoided. [#penalty_field]_ [#breach_field]_
   * - ``site-peak-consumption-price``
     - ``"260 EUR/MWh"``
     - Consumption peaks above the ``site-peak-consumption`` are penalized against this per-kW price. [#penalty_field]_
   * - ``site-peak-production``
     - ``{"sensor": 8}``
     - Current peak production.
       Costs from peaks below it are considered sunk costs. Default to 0 kW.
   * - ``site-peak-production-price``
     - ``"260 EUR/MWh"``
     - Production peaks above the ``site-peak-production`` are penalized against this per-kW price. [#penalty_field]_
   * - ``soc-minima-breach-price``
     - ``"120 EUR/kWh"``
     - Penalty for not meeting ``soc-minima`` defined in the flex-model. [#penalty_field]_ [#breach_field]_
   * - ``soc-maxima-breach-price``
     - ``"120 EUR/kWh"``
     - Penalty for not meeting ``soc-maxima`` defined in the flex-model. [#penalty_field]_ [#breach_field]_
   * - ``consumption-breach-price``
     - ``"10 EUR/kW"``
     - The price of breaching the ``consumption-capacity`` in the flex-model, useful to treat ``consumption-capacity`` as a soft constraint but still make the scheduler attempt to respect it. [#penalty_field]_ [#breach_field]_
   * - ``production-breach-price``
     - ``"10 EUR/kW"``
     - The price of breaching the ``production-capacity`` in the flex-model, useful to treat ``production-capacity`` as a soft constraint but still make the scheduler attempt to respect it. [#penalty_field]_ [#breach_field]_

.. [#old_sensor_field] The old field only accepted an integer (sensor ID).

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
At the moment, they have to be sent through the API (one of the endpoints to trigger schedule computation, or using the FlexMeasures client) or through the CLI (the command to add schedules).
We will soon work on the possibility to store (a subset of) these fields on the data model and edit them in the UI.


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
   * - ``soc-at-start``
     - ``"3.1 kWh"``
     - The (estimated) state of charge at the beginning of the schedule (defaults to 0). [#quantity_field]_
   * - ``soc-unit``
     - ``"kWh"`` or ``"MWh"``
     - The unit used to interpret any SoC related flex-model value that does not mention a unit itself (only applies to numeric values, so not to string values).
       However, we advise to mention the unit in each field explicitly (for instance, ``"3.1 kWh"`` rather than ``3.1``).
       Enumerated option only.
   * - ``soc-min``
     - ``"2.5 kWh"``
     - A constant lower boundary for all values in the schedule (defaults to 0). [#quantity_field]_
   * - ``soc-max``
     - ``"7 kWh"``
     - A constant upper boundary for all values in the schedule (defaults to max soc target, if provided). [#quantity_field]_
   * - ``soc-minima``
     - ``[{"datetime": "2024-02-05T08:00:00+01:00", value: "8.2 kWh"}]``
     - Set points that form lower boundaries, e.g. to target a full car battery in the morning (defaults to NaN values). [#maximum_overlap]_
   * - ``soc-maxima``
     - ``{"value": "51 kWh", "start": "2024-02-05T12:00:00+01:00", "end": "2024-02-05T13:30:00+01:00"}``
     - Set points that form upper boundaries at certain times (defaults to NaN values). [#minimum_overlap]_
   * - ``soc-targets``
     - ``[{"datetime": "2024-02-05T08:00:00+01:00", value: "3.2 kWh"}]``
     - Exact set point(s) that the scheduler needs to realize (defaults to NaN values).
   * - ``soc-gain``
     - ``[".1kWh"]``
     - SoC gain per time step, e.g. from a secondary energy source (defaults to zero).
   * - ``soc-usage``
     - ``[{"sensor": 23}]``
     - SoC reduction per time step, e.g. from a load or heat sink (defaults to zero).
   * - ``roundtrip-efficiency``
     - ``"90%"``
     - Below 100%, this represents roundtrip losses (of charging & discharging), usually used for batteries. Can be percent or ratio ``[0,1]`` (defaults to 100%). [#quantity_field]_
   * - ``charging-efficiency``
     - ``".9"``
     - Apply efficiency losses only at time of charging, not across roundtrip (defaults to 100%).
   * - ``discharging-efficiency``
     - ``"90%"``
     - Apply efficiency losses only at time of discharging, not across roundtrip (defaults to 100%).
   * - ``storage-efficiency``
     - ``"99.9%"``
     - This can encode losses over time, so each time step the energy is held longer leads to higher losses (defaults to 100%). Also read [#storage_efficiency]_ about applying this value per time step across longer time spans.
   * - ``prefer-charging-sooner``
     - ``True``
     - Tie-breaking policy to apply if conditions are stable, which signals a preference to charge sooner rather than later (defaults to True). It also signals a preference to discharge later. Boolean option only.
   * - ``prefer-curtailing-later``
     - ``True``
     - Tie-breaking policy to apply if conditions are stable, which signals a preference to curtail both consumption and production later, whichever is applicable (defaults to True). Boolean option only.
   * - ``power-capacity``
     - ``"50kW"``
     - Device-level power constraint. How much power can be applied to this asset (defaults to the Sensor attribute ``capacity_in_mw``). [#minimum_overlap]_
   * - ``consumption-capacity``
     - ``{"sensor": 56}``
     - Device-level power constraint on consumption. How much power can be drawn by this asset. [#minimum_overlap]_
   * - ``production-capacity``
     - ``"0kW"`` (only consumption)
     - Device-level power constraint on production. How much power can be supplied by this asset. For :abbr:`PV (photovoltaic solar panels)` curtailment, set this to reference your sensor containing PV power forecasts. [#minimum_overlap]_

.. [#quantity_field] Can only be set as a fixed quantity.

.. [#maximum_overlap] In case this field defines partially overlapping time periods, the maximum value is selected. See :ref:`variable_quantities`.

.. [#minimum_overlap] In case this field defines partially overlapping time periods, the minimum value is selected. See :ref:`variable_quantities`.

.. [#storage_efficiency] The storage efficiency (e.g. 95% or 0.95) to use for the schedule is applied over each time step equal to the sensor resolution. For example, a storage efficiency of 95 percent per (absolute) day, for scheduling a 1-hour resolution sensor, should be passed as a storage efficiency of :math:`0.95^{1/24} = 0.997865`.

For more details on the possible formats for field values, see :ref:`variable_quantities`.

Usually, not the whole flexibility model is needed.
FlexMeasures can infer missing values in the flex model, and even get them (as default) from the sensor's attributes.

You can add new storage schedules with the CLI command ``flexmeasures add schedule for-storage``.

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

For a hands-on tutorial on using some of the storage flex-model fields, head over to :ref:`tut_v2g` use case and `the API documentation for triggering schedules <../api/v3_0.html#post--api-v3_0-assets-(id)-schedules-trigger>`_.

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

You can add new shiftable-process schedules with the CLI command ``flexmeasures add schedule for-process``.

.. note:: Currently, the ``ProcessScheduler`` uses only the ``consumption-price`` field of the flex-context, so it ignores any site capacities and inflexible devices.


Work on other schedulers
--------------------------

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
