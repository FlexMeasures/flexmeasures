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

- the ``flex-context`` ― information about the system as a whole, in order to assess the value of activating flexibility.
- the ``flex model`` ― information about the state and possible actions of the flexible device. We will discuss these per scheduled device type.

This information goes beyond the usual time series recorded by an asset's sensors. It's being sent through the API when triggering schedule computation.
Some parts of it can be persisted on the asset & sensor model as attributes (that's design work in progress). 

Let's dive into the details ― what can you tell FlexMeasures about your optimization problem?

The flex-context
-----------------

The ``flex-context`` is independent of the type of flexible device that is optimized.
With the flexibility context, we aim to describe the system in which the flexible assets operate:


.. list-table::
   :header-rows: 1
   :widths: 20 25 90

   * - Field
     - Example value
     - Description 
   * - ``inflexible-device-sensors``
     - ``[3,4]``
     - Power sensors that are relevant, but not flexible, such as a sensor recording rooftop solar power connected behind the main meter, whose production falls under the same contract as the flexible device(s) being scheduled.
   * - ``consumption-price-sensor``
     - ``5``
     - The sensor that defines the price of consuming energy. This sensor can be recording market prices, but also CO₂ - whatever fits your optimization problem.
   * - ``production-price-sensor``
     - ``6``
     - The sensor that defines the price of producing energy.
   * - ``site-power-capacity``
     - ``"45kW"``
     - Maximum/minimum achievable power at the grid connection point [#asymmetric]_ (defaults to the Asset attribute ``capacity_in_mw``). A constant limit, or see [#sensor_field]_.
   * - ``site-consumption-capacity``
     - ``"45kW"``
     - Maximum consumption power at the grid connection point [#consumption]_ (defaults to the Asset attribute ``consumption_capacity_in_mw``). A constant limit, or see [#sensor_field]_. If ``site-power-capacity`` is defined, the minimum between the ``site-power-capacity`` and ``site-consumption-capacity`` will be used.
   * - ``site-production-capacity``
     - ``"0kW"``
     - Maximum production power at the grid connection point [#production]_ (defaults to the Asset attribute ``production_capacity_in_mw``). A constant limit, or see [#sensor_field]_. If ``site-power-capacity`` is defined, the minimum between the ``site-power-capacity`` and ``site-production-capacity`` will be used.


.. [#asymmetric] ``site-consumption-capacity`` and ``site-production-capacity`` allow defining asymmetric contracted transport capacities for each direction (i.e. production and consumption).
.. [#production] Example: with a connection capacity (``site-power-capacity``) of 1 MVA (apparent power) and a production capacity (``site-production-capacity``) of 400 kW (active power), the scheduler will make sure that the grid inflow doesn't exceed 400 kW.
.. [#consumption] Example: with a connection capacity (``site-power-capacity``) of 1 MVA (apparent power) and a consumption capacity (``site-consumption-capacity``) of 800 kW (active power), the scheduler will make sure that the grid outflow doesn't exceed 800 kW.

.. note:: If no (symmetric, consumption and production) site capacity is defined (also not as defaults), the scheduler will not enforce any bound on the site power. The flexible device can still has its own power limit defined in its flex-model.


The flex-models & corresponding schedulers
-------------------------------------------

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


The ``flex-model`` for storage describes to the scheduler what the flexible asset's state is,
and what constraints or preferences should be taken into account.

.. list-table::
   :header-rows: 1
   :widths: 20 25 90

   * - Field
     - Example value
     - Description 
   * - ``soc-at-start``
     - ``"3.1"``
     - The (estimated) state of charge at the beginning of the schedule (defaults to 0).
   * - ``soc-unit``
     - ``"kWh"`` or ``"MWh"``
     - The unit in which all SoC related flex-model values are to be interpreted.
   * - ``soc-min``
     - ``"2.5"``
     - A constant lower boundary for all values in the schedule (defaults to 0).
   * - ``soc-max``
     - ``"7"``
     - A constant upper boundary for all values in the schedule (defaults to max soc target, if provided)
   * - ``soc-minima``
     - ``[{"datetime": "2024-02-05T08:00:00+01:00", value: 8.2}]``
     - Set point(s) that form lower boundaries, e.g. to target a full car battery in the morning. Can be single values or a range (defaults to NaN values).
   * - ``soc-maxima``
     - ``{"value": 51, "start": "2024-02-05T12:00:00+01:00","end": "2024-02-05T13:30:00+01:00"}``
     - Set point(s) that form upper boundaries at certain times. Can be single values or a range (defaults to NaN values).
   * - ``soc-targets``
     - ``[{"datetime": "2024-02-05T08:00:00+01:00", value: 3.2}]``
     - Exact set point(s) that the scheduler needs to realize (defaults to NaN values).
   * - ``soc-gain``
     - ``.1kWh`` 
     - Encode SoC gain per time step. A constant gain every time step, or see [#sensor_field]_.
   * - ``soc-usage``
     - ``{"sensor": 23}`` 
     - Encode SoC reduction per time step. A constant loss every time step, or see [#sensor_field]_.
   * - ``roundtrip-efficiency``
     - ``"90%"``
     - Below 100%, this represents roundtrip losses (of charging & discharging), usually used for batteries. Can be percent or ratio ``[0,1]`` (defaults to 100%).
   * - ``charging-efficiency``
     - ``".9"``
     - Apply efficiency losses only at time of charging, not across roundtrip (defaults to 100%). A constant percentage at every step, or see [#sensor_field]_.
   * - ``discharging-efficiency``
     - ``"90%"``
     - Apply efficiency losses only at time of discharging, not across roundtrip (defaults to 100%). A constant percentage at every step, or see [#sensor_field]_.
   * - ``storage-efficiency``
     - ``"99.9%"``
     - This can encode losses over time, so each time step the energy is held longer leads to higher losses (defaults to 100%). A constant percentage at every step, or see [#sensor_field]_. Also read [#storage_efficiency]_ about applying this value per time step across longer time spans.
   * - ``prefer-charging-sooner``
     - ``True``
     - Policy to apply if conditions are stable (defaults to True, which also signals a preference to discharge later)
   * - ``power-capacity``
     - ``50kW``
     - Device-level power constraint. How much power can be applied to this asset (defaults to the Sensor attribute ``capacity_in_mw``). A constant limit, or see [#sensor_field]_.
   * - ``consumption-capacity``
     - ``{"sensor": 56}``
     - Device-level power constraint on consumption. How much power can be drawn by this asset. A constant limit, or see [#sensor_field]_.
   * - ``production-capacity``
     - ``0kW`` (only consumption)
     - Device-level power constraint on production. How much power can be supplied by this asset. A constant limit, or see [#sensor_field]_.

.. [#sensor_field] For some fields, it is possible to supply a sensor instead of one fixed value (``{"sensor": 51}``), which allows for more dynamic contexts, for instance power limits that change over time.

.. [#storage_efficiency] The storage efficiency (e.g. 95% or 0.95) to use for the schedule is applied over each time step equal to the sensor resolution. For example, a storage efficiency of 95 percent per (absolute) day, for scheduling a 1-hour resolution sensor, should be passed as a storage efficiency of :math:`0.95^{1/24} = 0.997865`.

Usually, not the whole flexibility model is needed. FlexMeasures can infer missing values in the flex model, and even get them (as default) from the sensor's attributes.

You can add new storage schedules with the CLI command ``flexmeasures add schedule for-storage``.

If you model devices that *buffer* energy (e.g. thermal energy storage systems connected to heat pumps), we can use the same flexibility parameters described above for storage devices.
However, here are some tips to model a buffer correctly:

   - Describe the thermal energy content in kWh or MWh.
   - Set ``soc-minima`` to the accumulative usage forecast.
   - Set ``charging-efficiency`` to the sensor describing the :abbr:`COP (coefficient of performance)` values.
   - Set ``storage-efficiency`` to a value below 100% to model (heat) loss.

What happens if the flex model describes an infeasible problem for the storage scheduler? Excellent question! It is highly important for a robust operation that these situations still lead to a somewhat good outcome.
From our practical experience, we derived a ``StorageFallbackScheduler``. It simplifies an infeasible situation by just starting to charge, discharge, or do neither,
depending on the first target state of charge and the capabilities of the asset.

Of course, we also log a failure in the scheduling job, so it's important to take note of these failures. Often, mis-configured flex models are the reason.

For a hands-on tutorial on using some of the storage flex-model fields, head over to :ref:`tut_v2g` use case and `the API documentation for triggering schedules <../api/v3_0.html#post--api-v3_0-sensors-(id)-schedules-trigger>`_.

Finally, are you interested in the linear programming details behind the storage scheduler? Then head over to :ref:`storage_device_scheduler`!
You can also review the current flex-model for storage in the code, at ``flexmeasures.data.schemas.scheduling.storage.StorageFlexModelSchema``.



Shiftable loads (processes)
^^^^^^^^^^^^^^^^^^^^^^^^^^

For *processes* that can be shifted or interrupted, but have to happen at a constant rate (of consumption), FlexMeasures provides the ``ShiftableLoad`` scheduler.
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
     - ``15kW`` 
     - Nominal power of the load.
   * - ``duration``
     - ``PT4H``
     - Time that the load needs to lasts.
   * - ``optimization_direction``
     - ``MAX``
     - Objective of the scheduler, to maximize (``MAX``) or minimize (``MIN``).
   * - ``time_restrictions``
     - ``[{"start": "2015-01-02T08:00:00+01:00", "duration": "PT2H"}]`` 
     - Time periods in which the load cannot be scheduled to run.
   * - ``process_type``
     - ``INFLEXIBLE``, ``BREAKABLE`` or ``SHIFTABLE``
     - Is the load inflexible? Or is there flexibility, to interrupt or shift it? 

You can review the current flex-model for processes in the code, at ``flexmeasures.data.schemas.scheduling.process.ProcessSchedulerFlexModelSchema``.

You can add new shiftable-process schedules with the CLI command ``flexmeasures add schedule for-process``.


Work on other schedulers
--------------------------

We believe the two schedulers (and their flex-models) we describe here are covering a lot of use cases already.
Here are some thoughts on further innovation:

- Writing your own scheduler. You can always write your own scheduler(see :ref:`plugin_customization`). You then might want to add your own flex model, as well. FlexMeasures will let the scheduler decide which flexibility model is relevant and how it should be validated. 
- We also aim to model situations with more than one flexible asset, and that have different types of flexibility (e.g. EV charging and smart heating in the same site). This is ongoing architecture design work, and therefore happens in development settings, until we are happy with the outcomes. Thoughts welcome :)
- Aggregating flexibility of a group of assets (e.g. a neighborhood) and optimizing its aggregated usage (e.g. for grid congestion support) is also an exciting direction for expansion.
