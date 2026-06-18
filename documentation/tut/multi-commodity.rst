.. _tut_multi_commodity:

A flex-modeling tutorial for storage: Multiple commodities (gas & electricity)
------------------------------------------------------------------------------

The :ref:`multi-feed storage tutorial <tut_multi_feed_storage>` showed that the ``flex-model`` can be a *list*, so that several devices are scheduled together in one call.
Those devices all acted on the same commodity (electricity). But many real sites mix commodities — electricity *and* gas, for instance — each with its own price.

FlexMeasures handles this with two ingredients:

- a ``commodity`` field on each device in the ``flex-model``, and
- a per-commodity price listing in the ``flex-context``.

In this tutorial we schedule a small hybrid site with one device on each commodity, and read back a cost breakdown that is tracked *per commodity*.
(For a more general introduction to flex modeling, see :ref:`describing_flexibility`. For the single-commodity, multi-device case, see :ref:`tut_multi_feed_storage`.)


The use case
============

A site has two flexible-ish devices, each acting on a different commodity:

- A **battery** on the ``electricity`` commodity: 20 kW power, 100 kWh capacity, 95% charging and discharging efficiency. It starts at 20 kWh and must reach 80 kWh by 23:00.
- A **gas boiler** on the ``gas`` commodity: it draws a **constant 1 kW** of gas every hour, modelled as a fixed load (it is not really flexible, but it still incurs a commodity cost we want to account for).

Prices are flat, but *different per commodity*:

- Electricity: **100 EUR/MWh** (consumption and production)
- Gas: **50 EUR/MWh**

We want the scheduler to optimise the battery against the electricity price, run the boiler at its fixed gas baseline, and report electricity and gas costs separately.


Building the flex model
=======================

As in the multi-feed tutorial, the ``flex-model`` is a **list** with one entry per device.
What is new here is the ``commodity`` field, which tells the scheduler *which price signal* applies to each device. It defaults to ``"electricity"``.

.. code-block:: json

    {
        "flex-model": [
            {
                "sensor": 1,
                "commodity": "electricity",
                "state-of-charge": {"sensor": 3},
                "soc-at-start": 20.0,
                "soc-min": 0.0,
                "soc-max": 100.0,
                "soc-targets": [
                    {"datetime": "2024-01-01T23:00:00+01:00", "value": 80.0}
                ],
                "power-capacity": "20 kW",
                "charging-efficiency": 0.95,
                "discharging-efficiency": 0.95
            },
            {
                "sensor": 2,
                "commodity": "gas",
                "power-capacity": "30 kW",
                "consumption-capacity": "30 kW",
                "production-capacity": "0 kW",
                "soc-usage": ["1 kW"],
                "soc-min": 0.0,
                "soc-max": 0.0,
                "soc-at-start": 0.0
            }
        ]
    }

Here, sensor ``1`` is the battery's power sensor, sensor ``2`` is the boiler's power sensor, and sensor ``3`` is the battery's instantaneous ``state-of-charge`` sensor (referenced from the battery entry so the scheduler records its charge level).

A few things to note:

- **The battery is a normal storage device** (``soc-at-start``, ``soc-min``, ``soc-max``, ``soc-targets``), tagged with ``"commodity": "electricity"``.
- **The boiler is modelled as a fixed load.** With ``soc-min`` and ``soc-max`` both 0, it can store nothing; ``soc-usage`` of ``1 kW`` forces it to consume exactly 1 kW of gas every hour, which the optimiser cannot change. ``production-capacity`` of 0 kW means it can never feed back.

The prices live in the ``flex-context``. For a single commodity you would pass ``consumption-price`` and ``production-price`` directly. For **multiple commodities**, you instead provide a ``commodities`` list, one entry per commodity:

.. code-block:: json

    {
        "flex-context": {
            "commodities": [
                {
                    "commodity": "electricity",
                    "consumption-price": "100 EUR/MWh",
                    "production-price": "100 EUR/MWh"
                },
                {
                    "commodity": "gas",
                    "consumption-price": "50 EUR/MWh",
                    "production-price": "50 EUR/MWh"
                }
            ]
        }
    }

Each device's costs are then evaluated against the prices of *its own* commodity: the battery against electricity, the boiler against gas.

.. note:: All commodities in one scheduling problem must share the same currency (here, EUR). The prices themselves can of course differ, and may be time series or sensors just like any other price in FlexMeasures.


Triggering the schedule
=======================

We schedule on the **site asset**, so that FlexMeasures considers both devices together in a single optimisation.

.. tabs::

    .. tab:: CLI

        .. code-block:: bash

            $ flexmeasures add schedule \
                --asset 1 \
                --start 2024-01-01T00:00+01:00 \
                --duration PT24H \
                --flex-model flex-model-multi-commodity.json \
                --flex-context flex-context-multi-commodity.json
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
                        "commodity": "electricity",
                        "state-of-charge": {"sensor": 3},
                        "soc-at-start": 20.0,
                        "soc-min": 0.0,
                        "soc-max": 100.0,
                        "soc-targets": [
                            {"datetime": "2024-01-01T23:00:00+01:00", "value": 80.0}
                        ],
                        "power-capacity": "20 kW",
                        "charging-efficiency": 0.95,
                        "discharging-efficiency": 0.95
                    },
                    {
                        "sensor": 2,
                        "commodity": "gas",
                        "power-capacity": "30 kW",
                        "consumption-capacity": "30 kW",
                        "production-capacity": "0 kW",
                        "soc-usage": ["1 kW"],
                        "soc-min": 0.0,
                        "soc-max": 0.0,
                        "soc-at-start": 0.0
                    }
                ],
                "flex-context": {
                    "commodities": [
                        {
                            "commodity": "electricity",
                            "consumption-price": "100 EUR/MWh",
                            "production-price": "100 EUR/MWh"
                        },
                        {
                            "commodity": "gas",
                            "consumption-price": "50 EUR/MWh",
                            "production-price": "50 EUR/MWh"
                        }
                    ]
                }
            }

    .. tab:: FlexMeasures Client

        Using the `FlexMeasures Client <https://pypi.org/project/flexmeasures-client/>`_:

        .. code-block:: python

            schedule = await client.trigger_and_get_schedule(
                asset_id=1,  # the site asset
                start="2024-01-01T00:00:00+01:00",
                duration="PT24H",
                flex_model=[
                    {
                        "sensor": 1,  # battery power sensor
                        "commodity": "electricity",
                        "state-of-charge": {"sensor": 3},  # battery SoC sensor
                        "soc-at-start": 20.0,
                        "soc-min": 0.0,
                        "soc-max": 100.0,
                        "soc-targets": [
                            {"datetime": "2024-01-01T23:00:00+01:00", "value": 80.0}
                        ],
                        "power-capacity": "20 kW",
                        "charging-efficiency": 0.95,
                        "discharging-efficiency": 0.95,
                    },
                    {
                        "sensor": 2,  # boiler power sensor
                        "commodity": "gas",
                        "power-capacity": "30 kW",
                        "consumption-capacity": "30 kW",
                        "production-capacity": "0 kW",
                        "soc-usage": ["1 kW"],
                        "soc-min": 0.0,
                        "soc-max": 0.0,
                        "soc-at-start": 0.0,
                    },
                ],
                flex_context={
                    "commodities": [
                        {
                            "commodity": "electricity",
                            "consumption-price": "100 EUR/MWh",
                            "production-price": "100 EUR/MWh",
                        },
                        {
                            "commodity": "gas",
                            "consumption-price": "50 EUR/MWh",
                            "production-price": "50 EUR/MWh",
                        },
                    ]
                },
            )

The scheduler returns one schedule per device (stored on sensors ``1`` and ``2``) and a single commitment-cost result that breaks the cost down per commodity.


What to expect
==============

The asset chart shows both commodities together, with the battery's stock level in between:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/multi-commodity.png
    :align: center
    :alt: Asset-level chart of the hybrid site, showing battery power, battery state of charge, and the gas boiler.
|

Reading the chart top to bottom:

- **Battery power (electricity)** charges at its full 20 kW for the first three hours, then makes one partial-power step to land exactly on the 80 kWh target, and sits idle for the rest of the day. In the final hour it discharges at −20 kW. Because the electricity price is flat, there is no cheaper window to wait for, so it simply charges as early as possible (``prefer-charging-sooner`` is on by default).
- **Battery state of charge** makes the effect of that power schedule explicit: the stock rises from the 20 kWh ``soc-at-start``, reaches the 80 kWh target during the morning, holds there through the idle hours, and drops in the final hour as the battery discharges. This is the charge level you would otherwise have to infer from the power curve.
- **Gas boiler (gas)** runs at exactly 1 kW every single hour. The ``soc-usage`` field makes this a fixed load that the optimiser cannot shift — its only effect on the result is the gas cost it incurs.

The schedules match the cost figures reported by the scheduler:

.. code-block:: text

    Electricity (battery)
      Net charge needed : 80 kWh − 20 kWh        = 60 kWh stored
      Grid draw         : 60 kWh ÷ 0.95          = 63.16 kWh
      Charge cost       : 63.16 kWh × 100 EUR/MWh ≈  6.32 EUR
      Discharge credit  : 20 kWh × 100 EUR/MWh   = −2.00 EUR
      Net electricity                            ≈  4.32 EUR

    Gas (boiler)
      Consumption       : 1 kW × 24 h            = 24 kWh
      Gas cost          : 0.024 MWh × 50 EUR/MWh =  1.20 EUR

    Total                                        =  5.52 EUR

The commitment-cost result keeps these as separate entries — ``electricity net energy`` (≈ 4.32 EUR) and ``gas net energy`` (1.20 EUR) — so you can always see how much each commodity contributed.
Because the gas price (50 EUR/MWh) is half the electricity price, serving the constant baseline with gas rather than electricity is the cheaper choice for that part of the load.

.. note:: This same pattern extends to more devices and more commodities. Add further entries to the ``flex-model`` list (each with its ``commodity``) and a matching entry in the ``flex-context`` ``commodities`` list. As long as all commodities share one currency, FlexMeasures optimises them together and reports each commodity's cost on its own.

We hope this demonstration helped to illustrate multi-commodity scheduling.
To revisit scheduling several devices that share a single commodity and stock, head back to :ref:`tut_multi_feed_storage`.
