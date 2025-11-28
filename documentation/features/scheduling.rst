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
     - |INFLEXIBLE_DEVICE_SENSORS.example|
     - .. include:: ../_autodoc/INFLEXIBLE_DEVICE_SENSORS.rst
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

You can add new shiftable-process schedules with the CLI command ``flexmeasures add schedule``. Make sure to use the ``--scheduler ProcessScheduler`` option to use the in-built process scheduler.

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
