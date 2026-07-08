.. _tut_multi_feed_storage:

A flex-modeling tutorial for storage: Multiple feeds into shared storage
------------------------------------------------------------------------

So far, our storage tutorials have considered a single power port charging and discharging a single battery.
But what if a buffer is fed by *more than one* device, each with its own power rating and efficiency?

This is a common situation in practice: a heat buffer (a hot water tank, say) is often fed by more than one heat source, and they all charge and discharge the *same* pool of stored heat.
FlexMeasures supports this through what we call **multiple feeds into a shared storage**: several flexible devices are scheduled together, while they all point at one shared ``state-of-charge`` sensor.

In this tutorial we will model exactly such a system: a heat buffer fed by a heat pump and a resistive heater, and let the scheduler decide which feeder to use, and when, taking each feeder's power rating into account while continuous heat demand drains the buffer.
(For a more general introduction to flex modeling, see :ref:`describing_flexibility`. For a single-device storage walk-through, see :ref:`tut_v2g`.)


The use case
============

Consider a single heat buffer with two feeders, and a single state-of-charge sensor for the buffer:

- Both feeders can charge the buffer, but with **different power ratings**.
- The buffer has a **single state of charge** that both feeders affect.
- The buffer continuously **loses heat to demand**, so the scheduler has to keep feeding it, not just reach a one-off target.
- The scheduler should recognise the shared storage and optimise accordingly, without duplicating baselines or costs.

Concretely, we model:

- A ``heat buffer`` asset, with an instantaneous ``state-of-charge`` sensor (in kWh, representing the buffer's thermal energy content).
- A ``heat pump`` asset, with its own ``power`` sensor, rated at 5 kW electrical, and a coefficient of performance (COP) of 3 — slow, but efficient.
- A ``resistive heater`` asset, with its own ``power`` sensor, rated at 15 kW electrical, and a COP of 1 — fast, but inefficient.
- Both feeders only ever add heat to the buffer; neither can extract heat back out of it.

The buffer starts at 20 kWh, may not drop below 20 kWh or exceed 22 kWh, and continuously loses heat to demand: 4 kW for most of the day, stepping up to 18 kW during a two-hour morning peak (e.g. showers and space heating first thing).
Its narrow operating band means the buffer has little room to pre-heat ahead of the peak, so the scheduler must actively respond to demand rather than simply filling up early.


Building the flex model
=======================

The key idea is that the ``flex-model`` is a **list**, with one entry per flexible device, plus one entry that describes the shared storage.
Each feeder entry references its own power sensor *and* the same ``state-of-charge`` sensor.
The final entry (without a power ``sensor``) carries the constraints that apply to the shared storage itself: the start, the bounds, and the ongoing usage.

.. code-block:: json

    {
        "flex-model": [
            {
                "sensor": 1,
                "state-of-charge": {"sensor": 3},
                "power-capacity": "5 kW",
                "production-capacity": "0 kW",
                "charging-efficiency": "300%"
            },
            {
                "sensor": 2,
                "state-of-charge": {"sensor": 3},
                "power-capacity": "15 kW",
                "production-capacity": "0 kW",
                "charging-efficiency": "100%"
            },
            {
                "state-of-charge": {"sensor": 3},
                "soc-at-start": 20.0,
                "soc-min": 20.0,
                "soc-max": 22.0,
                "soc-usage": [
                    {"start": "2024-01-01T00:00:00+01:00", "duration": "PT7H", "value": "4 kW"},
                    {"start": "2024-01-01T07:00:00+01:00", "duration": "PT2H", "value": "18 kW"},
                    {"start": "2024-01-01T09:00:00+01:00", "duration": "PT15H", "value": "4 kW"}
                ]
            }
        ]
    }

Here, sensors ``1`` and ``2`` are the power sensors of the heat pump and the resistive heater, respectively, and sensor ``3`` is the shared ``state-of-charge`` sensor on the heat buffer.

A few things to note:

- **Each device points at the same ``state-of-charge`` sensor.** This is what tells FlexMeasures that the devices share one storage. The scheduler links the energy balance of all feeds to that single state of charge, rather than tracking a separate stock per device.
- **The shared-storage entry has no power ``sensor``.** It only carries the storage-level fields (``soc-at-start``, ``soc-min``, ``soc-max``, ``soc-usage``), which describe the buffer as a whole and must therefore not be repeated per feeder.
- **Per-device efficiencies live in the device entries.** The heat pump's ``charging-efficiency`` of ``300%`` reflects its COP of 3 (1 kWh in yields 3 kWh of heat), while the resistive heater converts electricity to heat one-to-one at ``100%``. ``production-capacity`` of ``0 kW`` on both feeders means neither can extract heat back out of the buffer — they only ever charge it.
- **``soc-usage`` models the continuous heat demand.** Unlike a one-off ``soc-targets`` entry, it drains the buffer throughout the horizon, so the scheduler must keep feeding it rather than just reach a target once. Here it steps from a 4 kW baseline up to 18 kW for a two-hour morning peak.
- **The narrow gap between ``soc-min`` and ``soc-max``** leaves the buffer only 2 kWh of slack, so it cannot simply pre-heat well ahead of the morning peak. It also means that once the heat pump's power capacity is exhausted during the peak, the buffer has almost nowhere else to draw from — which is what forces the resistive heater into action.

.. note:: The ``state-of-charge`` sensor should have an instantaneous resolution (``PT0M``), since it records a stock value at a point in time rather than a quantity accumulated over an interval. See the ``state-of-charge`` field in :ref:`flex_models_and_schedulers`.

For the costs, we use a flat tariff in this example, identical at every hour, so price differences over time play no role in the schedule — only the buffer's physical constraints (capacity and ongoing usage) determine *when* each feeder runs.
The flat tariff still lets the scheduler tell the feeders apart: since the heat pump needs less electricity for the same amount of heat, it is the cheaper choice whenever either feeder could do the job.

.. code-block:: json

    {
        "flex-context": {
            "consumption-price": "100 EUR/MWh",
            "production-price": "100 EUR/MWh"
        }
    }


Triggering the schedule
=======================

We schedule on the **heat buffer asset**, so that FlexMeasures considers both feeders together as feeds into the buffer's shared stock.

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
                        "state-of-charge": {"sensor": 3},
                        "power-capacity": "5 kW",
                        "production-capacity": "0 kW",
                        "charging-efficiency": "300%"
                    },
                    {
                        "sensor": 2,
                        "state-of-charge": {"sensor": 3},
                        "power-capacity": "15 kW",
                        "production-capacity": "0 kW",
                        "charging-efficiency": "100%"
                    },
                    {
                        "state-of-charge": {"sensor": 3},
                        "soc-at-start": 20.0,
                        "soc-min": 20.0,
                        "soc-max": 22.0,
                        "soc-usage": [
                            {"start": "2024-01-01T00:00:00+01:00", "duration": "PT7H", "value": "4 kW"},
                            {"start": "2024-01-01T07:00:00+01:00", "duration": "PT2H", "value": "18 kW"},
                            {"start": "2024-01-01T09:00:00+01:00", "duration": "PT15H", "value": "4 kW"}
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
                asset_id=1,  # the heat buffer asset
                start="2024-01-01T00:00:00+01:00",
                duration="PT24H",
                flex_model=[
                    {
                        "sensor": 1,  # heat pump power sensor
                        "state-of-charge": {"sensor": 3},
                        "power-capacity": "5 kW",
                        "production-capacity": "0 kW",
                        "charging-efficiency": "300%",
                    },
                    {
                        "sensor": 2,  # resistive heater power sensor
                        "state-of-charge": {"sensor": 3},
                        "power-capacity": "15 kW",
                        "production-capacity": "0 kW",
                        "charging-efficiency": "100%",
                    },
                    {
                        "state-of-charge": {"sensor": 3},  # shared stock
                        "soc-at-start": 20.0,
                        "soc-min": 20.0,
                        "soc-max": 22.0,
                        "soc-usage": [
                            {"start": "2024-01-01T00:00:00+01:00", "duration": "PT7H", "value": "4 kW"},
                            {"start": "2024-01-01T07:00:00+01:00", "duration": "PT2H", "value": "18 kW"},
                            {"start": "2024-01-01T09:00:00+01:00", "duration": "PT15H", "value": "4 kW"},
                        ],
                    },
                ],
                flex_context={
                    "consumption-price": "100 EUR/MWh",
                    "production-price": "100 EUR/MWh",
                },
            )


The scheduler returns one schedule per feeder (stored on sensors ``1`` and ``2``), and the resulting state of charge (stored on the shared ``state-of-charge`` sensor ``3``).
Note that the costs are *not* duplicated per device: because the feeders feed one shared storage, FlexMeasures computes a single energy balance for the buffer.


What to expect
==============

With a flat tariff, the schedule is driven by the buffer's physical constraints (its narrow ``soc-min``/``soc-max`` band and the ongoing ``soc-usage``) *together with* each feeder's efficiency.
The scheduler specialises each feeder for the situation it is needed in:

- **The heat pump** covers the baseline heat demand (4 kW) throughout most of the day, drawing just over 1 kW of electricity thanks to its COP of 3. It is cheaper than the resistive heater for the same amount of heat, so the optimiser always prefers it when its power capacity allows.
- **The resistive heater** stays idle until the two-hour morning peak (18 kW), when demand exceeds what the heat pump can supply even at its own power capacity (15 kW of heat). It switches on for the first part of the peak, covering the shortfall the heat pump cannot. Towards the end of the peak, the optimiser instead lets the buffer's thin 2 kWh reserve (between ``soc-min`` and ``soc-max``) drain the rest of the way — that stored heat is "free" to use, so it is spent before calling on the resistive heater any longer than necessary.

So, even though both feeders *could* run at any time, the optimiser only calls on the resistive heater when neither the heat pump's power capacity nor the buffer's thin margin is enough to keep up with demand. The rest of the time, the cheaper, more efficient heat pump handles everything on its own.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/multi-feed-heat-buffer.png
    :align: center
|

Reading the chart top to bottom:

- **Feeders** (top panel) shows the power schedule of both feeds together. The heat pump runs at a modest, steady power level for most of the horizon to match the baseline demand, then ramps up to its own power capacity during the morning peak. The resistive heater stays idle until the peak, switches on alongside the heat pump to cover the shortfall, then drops back to idle again before the peak ends, once it's cheaper to draw on the buffer's remaining reserve instead.
- **Shared storage** (bottom panel) shows the *single* ``state-of-charge`` sensor that both feeders feed. It sits at the 22 kWh ``soc-max`` for most of the day, dips to the 20 kWh ``soc-min`` by the end of the morning peak — as its thin 2 kWh reserve is spent covering the tail end of the shortfall — and recovers immediately afterwards. This one curve is the combined effect of both feeds and the ongoing usage, which is exactly what "shared stock" means.

.. note:: This same pattern generalises beyond two feeders and beyond heat buffers. Any number of devices can feed a shared storage — as long as each device entry references the same ``state-of-charge`` sensor and a single entry carries the shared-stock constraints.

We hope this demonstration helped to illustrate how FlexMeasures schedules multiple feeds into a shared storage.
For modelling a single storage device in more depth, head back to :ref:`tut_v2g`.
To see how devices on *different* commodities (e.g. electricity and gas) are scheduled together, continue to :ref:`tut_multi_commodity`.
