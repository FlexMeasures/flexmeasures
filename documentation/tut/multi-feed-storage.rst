.. _tut_multi_feed_storage:

A flex-modeling tutorial for storage: Multiple feeds into shared stock
----------------------------------------------------------------------

So far, our storage tutorials have considered a single power port charging and discharging a single battery.
But what if a battery is fed by *more than one* inverter, each with its own power rating and efficiency?

This is a common situation in practice: a single storage tank or battery pack is connected to several converters, and they all charge and discharge the *same* pool of energy.
FlexMeasures supports this through what we call **multiple feeds into a shared stock**: several flexible devices are scheduled together, while they all point at one shared ``state-of-charge`` sensor.

In this tutorial we will model exactly such a system and let the scheduler decide which inverter to use, and when, taking each inverter's efficiency into account.
(For a more general introduction to flex modeling, see :ref:`describing_flexibility`. For a single-device storage walk-through, see :ref:`tut_v2g`.)


The use case
============

Consider a single battery with two inverters feeding it, and a single state-of-charge sensor for the battery:

- Both inverters can charge and discharge the battery, but with **different efficiencies**.
- The battery has a **single state of charge** that both inverters affect.
- The scheduler should recognise the shared stock and optimise accordingly, without duplicating baselines or costs.

Concretely, we model:

- A ``battery`` asset, with a ``power`` sensor (the aggregate) and an instantaneous ``state-of-charge`` sensor (in kWh).
- Two ``inverter`` assets (``inverter 1`` and ``inverter 2``), each with its own ``power`` sensor, rated at 20 kW.
- Inverter 1 is symmetric and efficient in both directions (95% charging, 95% discharging).
- Inverter 2 charges almost loss-free (99%) but discharges poorly (45%).

The battery starts at 20 kWh, may not drop below 10 kWh or exceed 200 kWh, and has to reach a target of 189 kWh at noon.


Building the flex model
=======================

The key idea is that the ``flex-model`` is a **list**, with one entry per flexible device, plus one entry that describes the shared stock.
Each inverter entry references its own power sensor *and* the same ``state-of-charge`` sensor.
The final entry (without a power ``sensor``) carries the constraints that apply to the shared stock itself: the start, the bounds, and the target.

.. code-block:: json

    {
        "flex-model": [
            {
                "sensor": 1,
                "state-of-charge": {"sensor": 4},
                "power-capacity": "20 kW",
                "charging-efficiency": 0.95,
                "discharging-efficiency": 0.95
            },
            {
                "sensor": 2,
                "state-of-charge": {"sensor": 4},
                "power-capacity": "20 kW",
                "charging-efficiency": 0.99,
                "discharging-efficiency": 0.45
            },
            {
                "state-of-charge": {"sensor": 4},
                "soc-at-start": 20.0,
                "soc-min": 10,
                "soc-max": 200.0,
                "soc-targets": [
                    {"datetime": "2024-01-01T12:00:00+01:00", "value": 189.0}
                ]
            }
        ]
    }

Here, sensors ``1`` and ``2`` are the power sensors of inverter 1 and inverter 2, respectively, and sensor ``4`` is the shared ``state-of-charge`` sensor on the battery.

A few things to note:

- **Each device points at the same ``state-of-charge`` sensor.** This is what tells FlexMeasures that the devices share one stock. The scheduler links the energy balance of all feeds to that single state of charge, rather than tracking a separate stock per device.
- **The shared-stock entry has no power ``sensor``.** It only carries the storage-level fields (``soc-at-start``, ``soc-min``, ``soc-max``, ``soc-targets``), which describe the battery as a whole and must therefore not be repeated per inverter.
- **Per-device efficiencies live in the device entries.** ``charging-efficiency`` and ``discharging-efficiency`` differ between the two inverters, which is exactly the difference the scheduler will exploit.

.. note:: The ``state-of-charge`` sensor should have an instantaneous resolution (``PT0M``), since it records a stock value at a point in time rather than a quantity accumulated over an interval. See the ``state-of-charge`` field in :ref:`flex_models_and_schedulers`.

For the costs, we use a flat tariff in this example, so price differences over time do not drive the schedule, only the efficiency differences do:

.. code-block:: json

    {
        "flex-context": {
            "consumption-price": "100 EUR/MWh",
            "production-price": "100 EUR/MWh"
        }
    }


Triggering the schedule
=======================

We schedule on the **battery asset**, so that FlexMeasures considers both inverters together as feeds into the battery's shared stock.

.. tabs::

    .. tab:: CLI

        .. code-block:: bash

            $ flexmeasures add schedule \
                --asset 1 \
                --start 2024-01-01T00:00+01:00 \
                --duration PT24H \
                --flex-model flex-model-multi-feed.json \
                --flex-context flex-context-flat-price.json
            New schedule is stored.

    .. tab:: API

        Example call: `[POST] http://localhost:5000/api/v3_0/assets/1/schedules/trigger <../api/v3_0.html#post--api-v3_0-assets-id-schedules-trigger>`_:

        .. code-block:: json

            {
                "start": "2024-01-01T00:00:00+01:00",
                "duration": "PT24H",
                "flex-model": [
                    {
                        "sensor": 1,
                        "state-of-charge": {"sensor": 4},
                        "power-capacity": "20 kW",
                        "charging-efficiency": 0.95,
                        "discharging-efficiency": 0.95
                    },
                    {
                        "sensor": 2,
                        "state-of-charge": {"sensor": 4},
                        "power-capacity": "20 kW",
                        "charging-efficiency": 0.99,
                        "discharging-efficiency": 0.45
                    },
                    {
                        "state-of-charge": {"sensor": 4},
                        "soc-at-start": 20.0,
                        "soc-min": 10,
                        "soc-max": 200.0,
                        "soc-targets": [
                            {"datetime": "2024-01-01T12:00:00+01:00", "value": 189.0}
                        ]
                    }
                ],
                "flex-context": {
                    "consumption-price": "100 EUR/MWh",
                    "production-price": "100 EUR/MWh"
                }
            }

    .. tab:: FlexMeasures Client

        Using the `FlexMeasures Client <https://pypi.org/project/flexmeasures-client/>`_:

        .. code-block:: python

            schedule = await client.trigger_and_get_schedule(
                asset_id=1,  # the battery asset
                start="2024-01-01T00:00:00+01:00",
                duration="PT24H",
                flex_model=[
                    {
                        "sensor": 1,  # inverter 1 power sensor
                        "state-of-charge": {"sensor": 4},
                        "power-capacity": "20 kW",
                        "charging-efficiency": 0.95,
                        "discharging-efficiency": 0.95,
                    },
                    {
                        "sensor": 2,  # inverter 2 power sensor
                        "state-of-charge": {"sensor": 4},
                        "power-capacity": "20 kW",
                        "charging-efficiency": 0.99,
                        "discharging-efficiency": 0.45,
                    },
                    {
                        "state-of-charge": {"sensor": 4},  # shared stock
                        "soc-at-start": 20.0,
                        "soc-min": 10,
                        "soc-max": 200.0,
                        "soc-targets": [
                            {"datetime": "2024-01-01T12:00:00+01:00", "value": 189.0}
                        ],
                    },
                ],
                flex_context={
                    "consumption-price": "100 EUR/MWh",
                    "production-price": "100 EUR/MWh",
                },
            )


The scheduler returns one schedule per inverter (stored on sensors ``1`` and ``2``), the resulting state of charge (stored on the shared ``state-of-charge`` sensor ``4``), and a single, aggregated commitment-cost result.
Note that the costs are *not* duplicated per device: because the inverters feed one shared stock, FlexMeasures computes a single energy balance and a single cost.


What to expect
==============

With a flat tariff, the schedule is driven purely by the efficiency differences between the two inverters.
The scheduler specialises each inverter for the operation it is best at:

- **Charging** happens through **inverter 2** (99% charging efficiency). It charges continuously from the start until the battery reaches the 189 kWh target at noon. Inverter 1 stays idle while charging.
- **Discharging** happens through **inverter 1** (95% discharging efficiency, versus only 45% for inverter 2). After the target is reached, inverter 1 discharges the battery back down towards its ``soc-min`` of 10 kWh. Inverter 2 stays idle while discharging.

So, even though both inverters *can* both charge and discharge, the optimiser uses inverter 2 only to charge and inverter 1 only to discharge — each inverter ends up doing what it is most efficient at.

Let's look at the whole battery at once. We can tell FlexMeasures which sensors to plot together on the **asset** by setting the battery's ``sensors_to_show`` attribute, grouping the two inverter power sensors into one panel and the shared state-of-charge sensor into another:

.. code-block:: python

    battery.sensors_to_show = [
        {"title": "inverters", "sensors": [inverter_1_power.id, inverter_2_power.id]},
        {"title": "shared storage", "sensors": [state_of_charge.id]},
    ]

The asset chart (the same Vega-Lite chart shown on the asset's page in the FlexMeasures UI) then renders both panels together:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/multi-feed-asset.png
    :align: center
    :alt: Asset-level chart of the battery, showing both inverters and the shared state of charge.
|

Reading the chart top to bottom:

- **Inverters** (top panel) shows the power schedule of both feeds together. Inverter 2 (the 99%-efficient charger) runs at its full +20 kW from the start of the horizon and tapers off in a single partial step once the target is reached — it only ever charges. Inverter 1 (the 95%-efficient discharger) stays idle while the battery fills, then runs at -20 kW late in the horizon — it only ever discharges. Even though both inverters *can* do both, the optimiser specialises each for the operation it is most efficient at.
- **Shared storage** (bottom panel) shows the *single* ``state-of-charge`` sensor that both inverters feed. It starts at the 20 kWh ``soc-at-start``, climbs while inverter 2 charges, reaches and briefly holds the 189 kWh target, and then falls as inverter 1 discharges — bottoming out at the 10 kWh ``soc-min``. This one curve is the combined effect of both feeds, which is exactly what "shared stock" means.

Plotting the inverters and the shared stock on the same asset chart makes the coordination obvious: the rise in the bottom panel lines up with inverter 2's charging in the top panel, and the fall lines up with inverter 1's discharging.

The net energy cost over the horizon is small (about 0.066 EUR at 100 EUR/MWh), and reflects only the energy lost to the inverter efficiencies, since charging and discharging happen at the same flat price.

.. note:: This same pattern generalises beyond two inverters and beyond batteries. Any number of devices can feed a shared stock — for example, several heat pumps charging one thermal buffer — as long as each device entry references the same ``state-of-charge`` sensor and a single entry carries the shared-stock constraints.

We hope this demonstration helped to illustrate how FlexMeasures schedules multiple feeds into a shared stock.
For modelling a single storage device in more depth, head back to :ref:`tut_v2g`.
