.. _flexibility_configuration:

Flexibility configuration
=========================

FlexMeasures describes an optimization problem with two complementary parts:
a system-wide :ref:`flex-context <flex_context>` and one or more device-specific
:ref:`flex-models <flex_models_and_schedulers>`. Together they describe what
flexibility is available, what limits it, and what outcome the scheduler should
optimize.

This page defines these concepts independently of how they are configured. They
can be persisted on assets, :ref:`edited in the UI <view_asset-data>`, or supplied
when triggering a schedule through the API, client, or CLI.


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


.. _variable_quantities:

Variable quantities
-------------------

Many API fields deal with variable quantities, for example, :ref:`flex-model <flex_models_and_schedulers>` and :ref:`flex-context <flex_context>` fields.
Unless stated otherwise, values of such fields can take one of the following forms:

- A fixed quantity, to describe steady constraints such as a physical power capacity.
  For example:

  .. code-block:: json

     {
         "power-capacity": "15 kW"
     }

- A variable quantity defined at specific moments in time, to describe dynamic constraints/preferences such as target states of charge.

  .. code-block:: json

     {
         "soc-targets": [
             {"datetime": "2024-02-05T08:00:00+01:00", "value": "8.2 kWh"},
             ...
             {"datetime": "2024-02-05T13:00:00+01:00", "value": "2.2 kWh"}
         ]
     }

- A variable quantity defined for specific time ranges, to describe dynamic constraints/preferences such as minimum state-of-charge requirements.

  .. code-block:: json

     {
         "soc-minima": [
             {"start": "2024-02-05T08:00:00+01:00", "duration": "PT2H", "value": "10.1 kWh"},
             ...
             {"start": "2024-02-05T13:00:00+01:00", "end": "2024-02-05T13:15:00+01:00", "value": "10.3 kWh"}
         ]
     }

  Note the two distinct ways of specifying a time period (``"end"`` in combination with ``"duration"`` also works).

  .. note:: In case a field defines partially overlapping time periods, FlexMeasures automatically resolves this.
            By default, time periods that are defined earlier in the list take precedence.
            Fields that deviate from this policy will note so explicitly.
            (For example, for fields dealing with capacities, the minimum is selected instead.)

- A reference to a sensor that records a variable quantity, which allows cross-referencing to dynamic contexts that are already recorded as sensor data in FlexMeasures. For instance, a site's contracted consumption capacity that changes over time.

  .. code-block:: json

     {
         "site-consumption-capacity": {"sensor": 55}
     }

  The unit of the data is specified on the sensor.

  A sensor reference can optionally include a source filter, so it keeps pointing at the right data even when multiple sources (e.g. a forecast and a schedule) record beliefs on the same sensor:

  .. code-block:: json

     {
         "site-consumption-capacity": {"sensor": 55, "source-types": ["forecaster"]}
     }

  The supported filter keys are:

  - ``source-types`` / ``exclude-source-types``: include or exclude sources by type (e.g. ``"forecaster"``, ``"scheduler"``, ``"user"``). **Recommended** over a specific ``source`` or ``sources`` ID, because forecasters and schedulers are versioned — a version bump gives new data a new source ID, but the source-type stays the same, so filters based on it don't need updating.
  - ``source-account``: a list of account IDs, to filter by the account(s) linked to data sources. Useful in multi-tenant setups where several accounts run their own forecasters or schedulers.
  - ``sources``: a list of specific data source IDs.
  - ``source``: a single specific data source ID.

  This is the same source filtering mechanism described under :ref:`sources`, just scoped to sensor references inside flex-model/flex-context fields rather than GET data endpoints.

A few fields don't hold a single variable quantity, but a *list* of them, whose values add up.
The ``soc-gain`` and ``soc-usage`` fields of the flex-model work this way, so that separate components (say, two loads draining the same buffer) can be described independently.
Each component takes any of the forms listed above, so a component defined for specific time ranges sits one level deeper than in those examples:

.. code-block:: json

   {
       "soc-usage": [
           "100 W",
           {"sensor": 23},
           [
               {"start": "2024-02-05T08:00:00+01:00", "duration": "PT2H", "value": "10.1 kW"},
               {"start": "2024-02-05T13:00:00+01:00", "duration": "PT2H", "value": "10.3 kW"}
           ]
       ]
   }


.. _flex_context:

The flex-context
-----------------

The ``flex-context`` is independent of the type of flexible device that is optimized, or which scheduler is used.
With the flexibility context, we aim to describe the system in which the flexible assets operate, such as its physical and contractual limitations.
For multi-commodity scheduling problems, the flex-context can be defined separately per commodity (e.g. electricity and gas). See :ref:`tut_multi_commodity` for a hands-on example.

A *non-electricity* commodity that defines no energy prices and no capacity (grid-connection) fields in the flex-context (e.g. a heat or steam network without a grid connection) is treated as an internal node:
its devices must balance each other at every time step, so everything produced into the node is consumed from it within the same time step.
Electricity is the exception: it is always assumed to be grid-connected, so electricity without a price raises an error rather than becoming an internal node.
Devices that convert between commodities (such as a CHP unit, gas boiler or electric heater) are described in the flex-model, one entry per commodity port, tied together by a ``coupling`` group. See :ref:`tut_converters` for a worked example flex-model.

Fields can have fixed values, but some fields can also point to sensors, so they will always represent the dynamics of the asset's environment (as long as that sensor has current data).
The full list of flex-context fields follows below.
For more details on the possible formats for field values, see :ref:`variable_quantities`.

.. figure:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot-asset-editflexcontext.png
   :align: center

   You can edit these settings also in the UI.

Where should you set these fields?
Within requests to the API or by editing the relevant asset in the UI.
If they are not sent in via the API (one of the endpoints triggering schedule computation), the scheduler will look them up on the flex-context field of the asset.
And if the asset belongs to a larger system (a hierarchy of assets), the scheduler will also search if parent assets have them set.



.. list-table::
   :header-rows: 1
   :widths: 20 25 90

   * - Field
     - Example value
     - Description
   * - ``commodity``
     - |COMMODITY_FLEX_CONTEXT.example|
     - .. include:: ../_autodoc/COMMODITY_FLEX_CONTEXT.rst
   * - ``inflexible-consumption``
     - |INFLEXIBLE_CONSUMPTION.example|
     - .. include:: ../_autodoc/INFLEXIBLE_CONSUMPTION.rst
   * - ``inflexible-production``
     - |INFLEXIBLE_PRODUCTION.example|
     - .. include:: ../_autodoc/INFLEXIBLE_PRODUCTION.rst
   * - ``inflexible-device-sensors``
     - |INFLEXIBLE_DEVICE_SENSORS.example|
     - .. include:: ../_autodoc/INFLEXIBLE_DEVICE_SENSORS.rst
   * - ``aggregate-consumption``
     - |AGGREGATE_CONSUMPTION.example|
     - .. include:: ../_autodoc/AGGREGATE_CONSUMPTION.rst
   * - ``aggregate-production``
     - |AGGREGATE_PRODUCTION.example|
     - .. include:: ../_autodoc/AGGREGATE_PRODUCTION.rst
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


.. _commodity_context_defaults:

Smart defaults for commodity-context grid connections
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For multi-commodity scheduling problems, each entry of the top-level ``commodities`` list is itself a flex-context (a "commodity context") describing the grid connection for that commodity.
A commodity context that leaves out some or all of its grid-connection fields (``consumption-price``, ``production-price``, ``site-consumption-capacity``, ``site-production-capacity`` and ``site-power-capacity``) gets sensible defaults for the missing fields, rather than failing or silently leaving the grid unconstrained.

As a rule of thumb, a price given for a direction (consumption or production) implies a grid connection in that direction, with an unlimited capacity unless a capacity is also given; a capacity given for a direction (without a price) implies a zero ``consumption-price`` or ``production-price`` (respectively) in that direction; and anything not implied by a given field defaults to "no connection" (a zero capacity, as a soft constraint).
The exception is ``site-power-capacity`` given on its own, which sets a *hard* (symmetric) capacity limit instead.

This leads to the following defaults, depending on which fields are explicitly given:

- **Nothing given** (e.g. just ``{"commodity": "gas"}``): both ``site-consumption-capacity`` and ``site-production-capacity`` default to zero, as soft constraints (a breach is possible, but penalized). ``site-power-capacity`` stays unlimited.
- **Only** ``consumption-price``: Then, ``site-power-capacity`` and ``site-consumption-capacity`` stay unlimited; ``site-production-capacity`` defaults to zero (soft).
- **Only** ``production-price``: the mirror image, for production.
- **Only** ``site-consumption-capacity``: Then, ``site-power-capacity`` stays unlimited; ``consumption-price`` defaults to zero; ``site-production-capacity`` (and, transitively, ``production-price``) default to zero.
- **Only** ``site-production-capacity``: the mirror image, for production.
- **Only** ``site-power-capacity``: Then, a *hard* constraint applies at that capacity, with ``site-consumption-capacity`` and ``site-production-capacity`` both set equal to it, and ``consumption-price``/``production-price`` defaulting to zero.

When several fields are given, each rule only fills in the fields not already determined by a given field, per direction (consumption/production) independently.
Giving all capacity fields is perfectly valid, too: the directional capacities then act as soft constraints, within the hard ``site-power-capacity`` limit.
As a safety net, ``consumption-price`` still defaults to zero if it remains unset after applying the rules above, since the scheduler requires a resolvable consumption price.

.. note:: Setting ``relax-constraints`` to ``False`` on a commodity context that ends up with a smart-defaulted 0 hard capacity can make the schedule infeasible; FlexMeasures logs a warning in that case.


.. _flex_models_and_schedulers:

The flex-models & corresponding schedulers
-------------------------------------------

FlexMeasures comes with a storage scheduler and a process scheduler, which work with flex models for storages and loads, respectively.

The storage scheduler is suitable for batteries and :abbr:`EV (electric vehicle)` chargers, and is automatically selected when scheduling an asset with one of the following asset types: ``"battery"``, ``"one-way_evse"`` and ``"two-way_evse"``.

The process scheduler is suitable for shiftable, breakable and inflexible loads, and is automatically selected for asset types ``"process"`` and ``"load"``.


We describe the respective flex models below.

These fields can be configured in the UI editor on the asset properties page or sent through the API (one of the endpoints to trigger schedule computation, or using the FlexMeasures client) or through the CLI (the command to add schedules).

.. figure:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_asset_flexmodel.png
   :align: center

   You can edit these settings also in the UI.


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
   * - ``commodity``
     - |COMMODITY_FLEX_MODEL.example|
     - .. include:: ../_autodoc/COMMODITY_FLEX_MODEL.rst
   * - ``coupling``
     - |COUPLING.example|
     - .. include:: ../_autodoc/COUPLING.rst
   * - ``coupling-coefficient``
     - |COUPLING_COEFFICIENT.example|
     - .. include:: ../_autodoc/COUPLING_COEFFICIENT.rst
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
   * - ``operation-modes``
     - |OPERATION_MODES.example|
     - .. include:: ../_autodoc/OPERATION_MODES.rst
   * - ``group``
     - |GROUP.example|
     - .. include:: ../_autodoc/GROUP.rst
   * - ``inflexible-consumption``
     - ``{"sensor": 3}``
     - .. include:: ../_autodoc/INFLEXIBLE_CONSUMPTION.rst
   * - ``inflexible-production``
     - ``{"sensor": 3}``
     - .. include:: ../_autodoc/INFLEXIBLE_PRODUCTION.rst

.. [#quantity_field] Can only be set as a fixed quantity.

.. [#soft_by_default] SoC minima and maxima are relaxed into soft constraints by default, receiving default breach prices, so the scheduler gets as close as possible to them when they cannot all be met. Setting ``relax-soc-constraints`` (or the umbrella ``relax-constraints``) to false keeps them hard, unless breach prices are supplied explicitly.

.. [#maximum_overlap] In case this field defines partially overlapping time periods, the maximum value is selected. See :ref:`variable_quantities`.

.. [#minimum_overlap] In case this field defines partially overlapping time periods, the minimum value is selected. See :ref:`variable_quantities`.

.. [#projecting_scheduling_constraints] Off-tick ``soc-targets``, ``soc-minima`` and ``soc-maxima`` are projected to the surrounding scheduling ticks. See :ref:`projecting_scheduling_constraints`.

.. [#zero_capacity] A value of zero is read as a statement about the device rather than an economic limit, but only when it holds for the whole scheduling window. A capacity that is zero throughout says the device cannot flow in that direction at all (a heat pump cannot produce), and is enforced strictly, even where device capacity relaxation is in effect. A zero covering only part of the window says "not right now" (keeping an EV charger idle during a calendar car reservation, say), and remains breachable at the applicable breach price like any other limit.

For more details on the possible formats for field values, see :ref:`variable_quantities`.


Intermediate power constraints
"""""""""""""""""""""""""""""""

In a multi-device flex-model list, a device entry may declare a ``group`` field referencing a group of devices, for example a hybrid inverter shared by a battery and PV installation, or a feeder shared by several devices. This lets you model an intermediate power constraint that sits between the individual devices and the site as a whole.

The recommended way to identify a group is by the **asset** that represents the shared equipment — a node in your asset tree, such as the inverter. This is the form that composes with flex-models stored on the asset tree and with multi-level hierarchies (see below), and it is what stored configurations naturally produce:

- ``{"asset": <asset id>}``: the group is identified by the flex-model entry on that asset (typically a sub-EMS/asset in the asset tree, such as the inverter in the example below). Such a group entry defines no power sensor of its own; instead, like any other asset-only entry, it may define ``consumption`` and/or ``production`` output sensor references (see below) on which the group's aggregate power gets saved.

Alternatively, a group can be identified by a **power sensor**. This is handy for compact, one-shot flex-models passed via the API, or when you already have an aggregate power sensor (e.g. a metered inverter feed) on which to record the group's schedule:

- ``{"sensor": <power sensor id>}``: the group is identified by a power sensor, which itself gets its own flex-model entry (typically passed alongside the device entries).

Either way, the group reference's target (asset or sensor) gets its own flex-model entry, defining constraints on the group's aggregate (summed) power:

- ``power-capacity`` on the group is a **hard** constraint (applied in both directions).
- ``consumption-capacity`` and ``production-capacity`` on the group are **soft** constraints, enforced with the same default breach prices used at the site level (10000 currency/kW); users cannot configure custom breach prices for groups.

The group's scheduled aggregate power is saved as a schedule output, following the same conventions used for any device's schedule output:

- For an asset-referenced group (an asset-only entry), the aggregate power is saved via its ``consumption`` and/or ``production`` output sensor references: with only ``consumption`` set, the full profile is saved consumption-positive; with only ``production`` set, the full profile is saved production-positive (i.e. sign-flipped before saving); with both set, the profile is split into its non-negative part (saved to ``consumption``) and its non-positive part (saved, as a positive magnitude, to ``production``).
- For a sensor-referenced group (whose flex-model entry has a ``sensor`` field), the aggregate power is saved directly to that sensor.

Groups can be nested (a group entry may itself reference a parent group), but cyclic references are rejected. Groups require a multi-device flex-model; they are rejected when scheduling a single sensor.

The recommended, tree-based way to configure a group is to define the whole flex-model on the asset tree in the DB, with no flex-model needed in the scheduling trigger at all: each device asset carries its own (partial) flex-model, including a ``group`` field pointing at the parent asset that represents the shared equipment, and that parent asset's own flex-model defines the group's constraints and output sensor(s). Triggering a schedule for the top-level site asset with an empty (or omitted) ``flex-model`` then collects the full configuration from the tree. For a hands-on walkthrough (including how to store flex-models on assets, and where the resulting schedules end up), see :ref:`tut_toy_schedule_group_constraints`.

The sensor-referenced form is convenient when you pass the whole flex-model in one go via the API. For example, a 2.5 kW hybrid inverter (sensor 5) shared by a battery (sensor 1) and PV installation (sensor 2), taken from `issue #2092 <https://github.com/FlexMeasures/flexmeasures/issues/2092>`_:

.. code-block:: json

    [
        {"sensor": 1, "power-capacity": "2 kW", "group": {"sensor": 5}},
        {"sensor": 2, "production-capacity": "2 kW", "consumption-capacity": "0 kW", "group": {"sensor": 5}},
        {"sensor": 5, "power-capacity": "2.5 kW"}
    ]

Here, the battery and PV installation may each individually schedule up to 2 kW, but their combined power flowing through the shared inverter is hard-limited to 2.5 kW.

.. _inflexible_devices_in_flex_model:

Inflexible devices in the flex-model
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Inflexible (measured) devices can be modelled in the flex-model too — for example, an unschedulable base load. To do so, model the inflexible device as its own asset and give its flex-model entry a single ``inflexible-consumption`` or ``inflexible-production`` reference to the sensor recording its power (the field name sets the sign convention, and source filters may be added). Such an entry carries no schedulable-device fields; it simply declares a fixed device whose power is accounted for. Like any device entry, it may set a ``commodity`` (defaulting to electricity), and its fixed power is then netted into that commodity's grid connection.

There are two places to declare an inflexible device, and the choice is about *where* it belongs rather than *what* it does. Listing its sensor in the flex-context's ``inflexible-consumption``/``inflexible-production`` fields describes plain site base load, which is a property of the connection. Giving it its own flex-model entry describes a device that sits somewhere specific in the asset tree — under a particular inverter, feeder or commodity — which is a property of the device. Both net the same fixed power into the grid connection.

The ``group`` field is optional on such an entry. Without it, the device is simply accounted for under the grid connection (just like listing its sensor in the flex-context's ``inflexible-consumption``/``inflexible-production`` fields, only declared on the asset instead). With it, the device *also* joins that group through the ordinary ``group`` field, exactly like a flexible member (the group's own flex-model entry, defining its capacities, must still be present), so that its fixed load or supply additionally counts towards the group's intermediate power constraint — for example, a base load sitting behind the same inverter or feeder as a battery.


Usually, not the whole flexibility model is needed.
FlexMeasures can infer missing values in the flex model, and even get them (as default) from the sensor's attributes.

You can add new storage schedules with the CLI command ``flexmeasures add schedule``.

If you model devices that *buffer* energy (e.g. thermal energy storage systems connected to heat pumps), we can use the same flexibility parameters described above for storage devices.
However, here are some tips to model a buffer correctly:

   - Describe the thermal energy content in kWh or MWh.
   - Set ``soc-minima`` to the accumulative usage forecast.
   - Set ``charging-efficiency`` to the sensor describing the :abbr:`COP (coefficient of performance)` values.
   - Set ``storage-efficiency`` to a value below 100% to model (heat) loss.

   For a hands-on example of a heat buffer fed by multiple devices, see :ref:`tut_multi_feed_storage`.

If the flex model describes an infeasible problem for the storage scheduler, the failure should remain visible.
By default, ``soc-minima`` and ``soc-maxima`` are relaxed into soft constraints, so the scheduler can still return a useful schedule when these boundaries cannot be fully met.
Setting either ``relax-soc-constraints`` or ``relax-constraints`` to ``false`` in the flex-context keeps them as hard constraints.
Exact ``soc-targets``, physical ``soc-min`` / ``soc-max`` bounds, and ``power-capacity`` (in the flex-model) and ``site-power-capacity`` (in the flex-context) remain hard constraints.
If those hard constraints make the problem infeasible, the scheduling job fails instead of producing a fallback schedule.

It is important to take note of these failures. Often, misconfigured flex models are the reason.

For a hands-on tutorial on using some of the storage flex-model fields, head over to :ref:`tut_v2g` use case and `the API documentation for triggering schedules <../api/v3_0.html#post--api-v3_0-assets-id-schedules-trigger>`_.
For further hands-on examples, see :ref:`tut_multi_feed_storage` (multiple devices feeding one shared storage) and :ref:`tut_multi_commodity` (devices on different commodities scheduled together).

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
