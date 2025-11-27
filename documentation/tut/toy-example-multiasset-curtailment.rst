.. _tut_toy_schedule_multiasset_curtailment:



Toy example III: PV curtailment an Multi-asset scheduling
================================================================

What if the solar production is curtailable? We could turn it off when prices are negative, which happens more often now. 

This is useful, but also an exciting next step for our modeling: Curtailing its output makes the PV inverter a flexible control, so with the battery, there are now two flexible assets.

We are now moving to multi-asset scheduling. We'll officially be scheduling the building (asset 2).

We will do this step by step. First, we demonstrate PV curtailment by itself.

Then, we will combine it with the battery scheduling from before and run a multi-asset scheduling example.

.. note:: Another situation where PV curtailment is needed is  we'd need this is when the DSO does not allow any power feed-in, so we should not schedule any feed-in. A local gateway will usually prevent PV power being fed into the grid - but FlexMeasures should of course provide schedules taking this setting into account.


PV curtailment
---------------------------------------
We start by curtailing the PV asset only.

To make the PV asset curtailable, we tell FlexMeasures that the PV (represented by sensor 3) can only pick production values between 0 and the production forecast recorded on sensor 3.
We store the resulting schedule on sensor 3, as well (the FlexMeasures UI will still be able to distinguish forecasts from schedules).

Also, we want to create a situation with negative prices, so curtailment makes sense. We can pass into the ``flex-context`` a price profile with negative prices during some hours of the day.

.. tabs::

    .. tab:: CLI

        .. code-block:: bash

            $ # this flex context has negative prices between 12:00 and 14:00
            $ echo '''{
            "consumption-price": [
                {"start": "'${TOMORROW}'T00:00+00", "duration": "PT24H", "value": "10 EUR/MWh"}
            ],
            "production-price": [
                {"start": "'${TOMORROW}'T05:00+00", "duration": "PT7H", "value": "4 EUR/MWh"},
                {"start": "'${TOMORROW}'T12:00+00", "duration": "PT2H", "value": "-10 EUR/MWh"},
                {"start": "'${TOMORROW}'T14:00+00", "duration": "PT7H", "value": "4 EUR/MWh"}
            ]
            }''' > tutorial3-priceprofile-flex-context.json
            $ docker cp tutorial3-priceprofile-flex-context.json flexmeasures-server-1:/app/ 

            $ # Scheduling only the PV sensor
            $ docker exec -it flexmeasures-server-1 flexmeasures add schedule --sensor 3 \
            --start ${TOMORROW}T07:00+00:00 --duration PT12H \
            --flex-model '{"consumption-capacity": "0 kW", "production-capacity": {"sensor": 3, "source": 4}}'\
            --flex-context tutorial3-priceprofile-flex-context.json 

    .. tab:: API

        Example call: `[POST] http://localhost:5000/api/v3_0/sensors/3/schedules/trigger <../api/v3_0.html#post--api-v3_0-sensors-(id)-schedules-trigger>`_ (update the start date to tomorrow):

        .. code-block:: json
            :emphasize-lines: 14-18

            {
                "start": "2025-11-18T07:00+01:00",
                "duration": "PT12H",
                "flex-model": [
                    {
                        "consumption-capacity": "0 kW",
                        "production-capacity": {"sensor": 3, "source": 4},
                    }
                ],
                "flex-context": {
                    "consumption-price": [
                        {"start": "2025-11-18T00:00+00", "duration": "PT24H", "value": "10 EUR/MWh"}
                    ],
                    "production-price": [
                        {"start": "2025-11-18T05:00+00", "duration": "PT7H", "value": "4 EUR/MWh"},
                        {"start": "2025-11-18T12:00+00", "duration": "PT2H", "value": "-10 EUR/MWh"},
                        {"start": "2025-11-18T14:00+00", "duration": "PT7H", "value": "4 EUR/MWh"}
                    ]
                }
            }

    .. tab:: FlexMeasures Client

        Using the `FlexMeasures Client <https://pypi.org/project/flexmeasures-client/>`_:

        .. code-block:: bash

            pip install flexmeasures-client

        .. code-block:: python

            import asyncio
            from datetime import date, timedelta
            from flexmeasures_client import FlexMeasuresClient as Client
            
            async def client_script():
                schedule = await client.trigger_and_get_schedule(
                    sensor_id=3,  # PV production sensor
                    start=f"{date.today().isoformat()}T07:00+01:00",
                    duration="PT12H",
                    flex_model=[
                        {
                            "consumption-capacity": "0 kW",
                            "production-capacity": {"sensor": 3, "source": 4},
                        }
                    ],
                    flex_context={
                        "consumption-price": [
                            {"start": "2025-11-18T00:00+00", "duration": "PT24H", "value": "10 EUR/MWh"}
                        ],
                        "production-price": [
                            {"start": "2025-11-18T05:00+00", "duration": "PT7H", "value": "4 EUR/MWh"},
                            {"start": "2025-11-18T12:00+00", "duration": "PT2H", "value": "-10 EUR/MWh"},
                            {"start": "2025-11-18T14:00+00", "duration": "PT7H", "value": "4 EUR/MWh"}
                        ]
                    },
                )

.. note:: We are showing a different way to pass time series to FlexMeasures here - we can specify segments ("blocks") where for some duration some price holds. This is often more convenient than passing in a full time series, especially when many values are identical.

Great. Let's see what we made:

.. code-block:: bash
    
    echo "[TUTORIAL-RUNNER] showing PV schedule ..."
    docker exec -it flexmeasures-server-1 flexmeasures show beliefs --sensor 3 --start ${TOMORROW}T07:00:00+00:00 --duration PT12H

    Beliefs for Sensor 'production' (ID 3).
    Data spans 12 hours and starts at 2025-11-18 07:00:00+00:00.
    The time resolution (x-axis) is 15 minutes.
    ┌────────────────────────────────────────────────────────────┐
    │                   ▗▀▀▀▀▌                                   │
    │              ▗▀▀▀▀▘    ▌                                   │ 0.2MW
    │          ▄▄▄▄▌         ▚                                   │
    │         ▞              ▐                                   │
    │    ▗▀▀▀▀▘              ▐          ▐▀▀▀▜                    │
    │    ▞                   ▐          ▐    ▌                   │
    │▀▀▀▀▘                   ▐          ▌    ▝▀▀▀▜               │
    │                        ▐          ▌        ▝▖              │
    │                        ▐          ▌         ▚              │
    │                         ▌         ▌         ▝▀▀▀▜          │
    │                         ▌         ▌              ▌         │
    │                         ▌        ▐               ▚         │
    │                         ▌        ▐               ▝▀▀▀▜     │
    │                         ▌        ▐                    ▌    │
    │                         ▌        ▐                    ▝▀▀▀▀│
    │                         ▚        ▐                         │
    │▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▐▄▄▄▄▄▄▄▄▌▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁│ -0.0MW
    └────────────────────────────────────────────────────────────┘
            09:00          12:00          15:00           18:00
                    ██ production (toy-solar)


The curtailment is visible between 12:00 and 14:00, when prices are negative.



Multi-asset (building-level) Scheduling
--------------------------------------- 

Now - we want to schedule the complete building, including two flexible assets: the battery and the PV inverter.

This means we schedule on the building level (asset 2) and include both the target sensors for both flexible assets in the flex-model.

Note that we are still passing in the flex-context with block price profiles here, as we did in the previous example - with one block of negative prices.

.. tabs::

    .. tab:: CLI

        .. code-block:: bash
            :emphasize-lines: 2,6
            
            $ flexmeasures add schedule \
                --asset 2 \
                --start ${TOMORROW}T07:00+00:00 \
                --duration PT12H \
                --flex-model '[{"sensor": 3, "consumption-capacity": "0 kW", "production-capacity": {"sensor": 3, "source": 4}}, {"sensor": 2, "soc-at-start": "225 kWh", "soc-min": "50 kWh"}]'\
                --flex-context tutorial3-priceprofile-flex-context.json 
            New schedule is stored.

    .. tab:: API

        Example call: `[POST] http://localhost:5000/api/v3_0/sensors/2/schedules/trigger <../api/v3_0.html#post--api-v3_0-sensors-(id)-schedules-trigger>`_ (update the start date to tomorrow):

        .. code-block:: json

            {
                "start": "2025-06-11T07:00+01:00",
                "duration": "PT12H",
                "flex-model": [
                    {
                        "sensor": 3,
                        "consumption-capacity": "0 kW",
                        "production-capacity": {"sensor": 3, "source": 4},
                    }
                    {
                        "sensor": 2,
                        "soc-at-start": "225 kWh",
                        "soc-min": "50 kWh"
                    },
                ],
                "flex-context": {
                    "consumption-price": [
                        {"start": "2025-11-18T00:00+00", "duration": "PT24H", "value": "10 EUR/MWh"}
                    ],
                    "production-price": [
                        {"start": "2025-11-18T05:00+00", "duration": "PT7H", "value": "4 EUR/MWh"},
                        {"start": "2025-11-18T12:00+00", "duration": "PT2H", "value": "-10 EUR/MWh"},
                        {"start": "2025-11-18T14:00+00", "duration": "PT7H", "value": "4 EUR/MWh"}
                    ]
                }
            }

    .. tab:: FlexMeasures Client

        Using the `FlexMeasures Client <https://pypi.org/project/flexmeasures-client/>`_:

        .. code-block:: bash

            pip install flexmeasures-client

        .. code-block:: python
            :emphasize-lines: 2

            schedule = await client.trigger_and_get_schedule(
                asset_id=2,  # Toy building (asset ID)
                start=f"{date.today().isoformat()}T07:00+01:00",
                duration="PT12H",
                flex_model=[
                    {
                        "sensor": 3,  # solar production (sensor ID)
                        "consumption-capacity": "0 kW",
                        "production-capacity": {"sensor": 3, "source": 4},
                    },
                    {
                        "sensor": 2,  # battery power (sensor ID)
                        "soc-at-start": "225 kWh",
                        "soc-min": "50 kWh",
                    },
                ],
                flex_context={
                        "consumption-price": [
                            {"start": "2025-11-18T00:00+00", "duration": "PT24H", "value": "10 EUR/MWh"}
                        ],
                        "production-price": [
                            {"start": "2025-11-18T05:00+00", "duration": "PT7H", "value": "4 EUR/MWh"},
                            {"start": "2025-11-18T12:00+00", "duration": "PT2H", "value": "-10 EUR/MWh"},
                            {"start": "2025-11-18T14:00+00", "duration": "PT7H", "value": "4 EUR/MWh"}
                        ]
                    },
            )

What do we expect? The battery should soak up all solar power in times of negative prices, even emptying itself earlier, if needed, to make space for solar production.
The PV inverter should then not need to curtail any production, as the battery can absorb it all.

And the battery should get rid of this energy again when prices go up later in the day.

We can confirm this is the case on the updated scheduling in the `FlexMeasures UI <http://localhost:5000/assets/2/graphs>`_:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-multiasset-negativeprices.png
    :align: center
|

.. note:: We are not displaying the price profile blocks on the graphs page, but the day ahead prices which this schedule did not consider. By passing the price profile blocks in the ``flex-context``, we are overwriting them for this calculation.

And here is the CLI version:

.. code-block:: bash
    
    Beliefs for Sensors production (ID 3) and discharging (ID 2).
    Data spans 12 hours and starts at 2025-11-18 07:00:00+00:00.
    The time resolution (x-axis) is 15 minutes.
    ┌────────────────────────────────────────────────────────────┐
    │                                                         ▛▀▀│
    │                                                        ▐   │ 0.4MW
    │                                                        ▞   │
    │                                                        ▌   │
    │                       ▄▖                              ▐    │
    │                      ▐ ▌                              ▐    │
    │              ▗▄▄▄▄▞▀▀▐▀▚▚▄▄▄▄▖                        ▞    │ 0.2MW
    │    ▗▄▄▄▄▛▀▀▀▀▘       ▞ ▐     ▝▀▀▀▀▚▄▄▄▄▖              ▌    │
    │▀▀▀▀▘                 ▌ ▐               ▝▀▀▀▀▖         ▌    │
    │                      ▌ ▐                    ▝▀▀▀▀▖   ▗▘    │
    │                     ▐  ▐                         ▝▀▀▀▐▄▄▄▄▄│
    │▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▀▁▁▝▖▁▁▁▁▁▁▁▁▁▗▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▟▁▁▁▁▁│ -0.0MW
    │                         ▌         ▞                        │
    │                         ▌         ▌                        │
    │                         ▌        ▐                         │
    │                         ▌        ▐                         │
    │                         ▐▄▄▄▄▀▀▀▀▘                         │ -0.2MW
    └────────────────────────────────────────────────────────────┘
            09:00          12:00          15:00           18:00
    ██ production (toy-solar)   ██ discharging (toy-battery)



Okay, that worked nicely. We scheduled two assets at once, and the battery absorbed all solar production during negative price periods.
|

For a last iteration, what if we remove the price blocks from the flex-context? Then we fall back to day-ahead prices (sensor 1) already set on the building asset's flex context (see :ref:`tut_load_data`).

What should we expect then? The battery should still cycle grid power to make the most our of some price spreads on the DA market.
It should probably absorb solar power as well in the moments where it isn't selling to the grid at high prices.

.. note:: In commercial settings, the price for production (feed-in) is often lower than the price for consumption. This reduces opportunities for cycling and increases the likelihood that an optimized battery would soak up solar power.

For the schedule shown below, we did not use any flex-context with blocked price profiles, but we made the battery larger (``"soc-max": "900 kWh"``) to showcase the battery soaking up solar production.
In the hours between noon and 2pm, the profiles match well.

.. code-block:: bash

    Beliefs for Sensors production (ID 3) and discharging (ID 2).
    Data spans 12 hours and starts at 2025-11-19 07:00:00+00:00.
    The time resolution (x-axis) is 15 minutes.
    ┌────────────────────────────────────────────────────────────┐
    │                                                       ▐▀▀▀▀│
    │                                                       ▐    │ 0.4MW
    │▖                                                      ▐    │
    │▝▖                                                     ▞    │
    │ ▐             ▄▄▄▄▖   ▄▖                              ▌    │
    │ ▐             ▌   ▌  ▐ ▌                              ▌    │
    │ ▐            ▗▌▄▄▄▐▀▀▐▀▚▚▄▄▄▄▖                        ▌    │ 0.2MW
    │  ▌ ▗▄▄▄▄▛▀▀▀▀▐    ▐  ▞ ▐     ▝▀▀▀▀▚▄▄▄▄▖              ▌    │
    │▀▀▌▀▘         ▐    ▝▖ ▌ ▐               ▝▀▀▀▀▖        ▐     │
    │  ▚           ▐     ▌ ▌ ▐                    ▝▀▀▀▀▖   ▐     │
    │  ▐           ▌     ▌▐  ▐                         ▝▀▀▀▐▄▄▄▄▄│
    │▁▁▐▄▄▄▄▄▄▄▄▄▄▄▌▁▁▁▁▁▚▀▁▁▝▖▁▁▁▁▁▁▁▁▁▗▄▄▖▁▗▄▄▄▄▄▄▄▄▄▄▄▄▞▀▁▁▁▁▁│ -0.0MW
    │                         ▌         ▞  ▐ ▌                   │
    │                         ▌         ▌   ▛                    │
    │                         ▌        ▐                         │
    │                         ▌        ▐                         │
    │                         ▐▄▄▄▄▀▀▀▀▘                         │ -0.2MW
    └────────────────────────────────────────────────────────────┘
            09:00          12:00          15:00           18:00
    ██ production (toy-solar)   ██ discharging (toy-battery)






Now our tutorial example has grown quite a bit. This step included scheduling multiple assets (battery and PV inverter), as well as demonstrating a different kind of flexibility: PV curtailment.

In :ref:`tut_v2g`, we will temporarily pause giving you tutorials you can follow step-by-step. We feel it is time to pay more attention to the power of the flex-model, and illustrate its effects.