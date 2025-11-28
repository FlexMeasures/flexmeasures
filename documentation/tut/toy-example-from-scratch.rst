.. _tut_toy_schedule:

Toy example I: Scheduling a battery, from scratch
===============================================

Let's walk through an example from scratch! We'll optimize a 12h-schedule for a battery that is half full.

Okay, let's get started!

.. note:: You can copy the commands by hovering on the top right corner of code examples. You'll copy only the commands, not the output!

.. note:: If you haven't run through :ref:`tut_install_load_data` yet, do that first. There, we added power prices for a 24h window.




Make a schedule
---------------------------------------

After going through the setup, we can finally create the schedule, which is the main benefit of FlexMeasures (smart real-time control).

We'll ask FlexMeasures for a schedule for our battery, specifically to store it on the (dis)charging sensor (ID 2).

To keep this short, we'll only ask for a 12-hour window starting at 7am. Finally, the scheduler should know what the state of charge of the battery is when the schedule starts (50%) and also that the SoC should never fall below 50 kWh.

There is more information being used by the scheduler, such as the battery's capacity, roundtrip-efficiency and energy prices, but we added that when we created the sensor (see :ref:`tut_load_data`).

.. note:: 
    You can see here that you have the choice to put such information in the flex model when asking for a schedule, or store it on the asset/sensor itself.
    *What should go into the flex model on the asset, and what do you want to send when asking for a schedule?*
    It is your call! Things that do not change often could be stored on the asset. Here, ``soc-min`` could actually move there, if you believe this is usually going to be your preferred lower limit...
    
    Do note that what you send while asking for a schedule always takes precedence over what is stored on the asset. 

.. tabs::

    .. tab:: CLI

        .. code-block:: bash

            $ flexmeasures add schedule \
                --sensor 2 \
                --start ${TOMORROW}T07:00+01:00 \
                --duration PT12H \
                --soc-at-start 50% \
                --flex-model '{"soc-min": "50 kWh"}'
            New schedule is stored.
        
        .. note:: If you ever have a larger flex context and/or flex model, this data can also be stored in files instead of passing them inline. See this example below:

        .. code-block:: console

            $ cat my-flex-model.json  # assuming you created this file 
            {
                "roundtrip-efficiency": "80%",
                "soc-min": "0 kWh",
                "soc-max": "400 kWh",
                "soc-maxima": [
                    {
                        "value": "51 kWh",
                        "start": "2024-02-04T10:35:00+01:00",
                        "end": "2024-02-05T04:25:00+01:00"
                    }
                ],
                "soc-usage": [{"sensor": 73}]
            }
            
            $ flexmeasures add schedule \                                      
                --sensor 2 \
                --start 2024-02-04T07:00+01:00 \
                --duration PT24H \
                --soc-at-start 50% \
                --flex-model my-flex-model.json


    .. tab:: API

        Example call: `[POST] http://localhost:5000/api/v3_0/sensors/3/schedules/trigger <../api/v3_0.html#post--api-v3_0-sensors-id-schedules-trigger>`_ (update the start date to tomorrow):

        .. code-block:: json

            {
                "start": "2025-11-11T07:00+01:00",
                "duration": "PT12H",
                "flex-model": [
                    "sensor": 2,
                    "soc-at-start": "225kWh",
                    "soc-min": "50 kWh"
                ]
            }

        .. note:: You can try this right in Swagger UI, too! You should find it at `http://localhost:5000/api/v3_0/docs <http://localhost:5000/api/v3_0/docs>`_ after starting FlexMeasures locally.

    .. tab:: FlexMeasures Client

        Using the `FlexMeasures Client <https://pypi.org/project/flexmeasures-client/>`_:

        .. code-block:: bash

            pip install flexmeasures-client

        .. code-block:: python
            import asyncio
            from datetime import date, timedelta
            from flexmeasures_client import FlexMeasuresClient as Client
                        

            async def client_script():
                client = Client(
                    email="toy-user@flexmeasures.io",
                    password="toy-password",
                    host="localhost:5000",
                )
                schedule = await client.trigger_and_get_schedule(
                    sensor_id=2,  # battery discharging power sensor
                    start=f"{(date.today() + timedelta(days=1)).isoformat()}T07:00+01:00",
                    duration="PT12H",
                    flex_model={
                        "soc-at-start": "225 kWh",
                        "soc-min": "50 kWh",
                    },
                    flex_context={},
                )
                print(schedule)
                await client.close()

            asyncio.run(client_script())

        .. note:: Paste this into a file and it should run! 

.. note:: We already specified what to optimize against by having set the consumption price sensor in the flex-context of the battery (see :ref:`tut_load_data`).

Great. Let's see what we made:

.. code-block:: bash

    Beliefs for Sensor 'discharging' (ID 2).
    Data spans 12 hours and starts at 2025-11-29 07:00:00+01:00.
    The time resolution (x-axis) is 15 minutes.
    ┌────────────────────────────────────────────────────────────┐
    │     ▛▀▜            ▞▀▀▌                               ▐▀▀▚ │ 0.5MW
    │     ▌  ▌           ▌  ▌                               ▐  ▐ │
    │    ▗▘  ▌           ▌  ▌                               ▐  ▐ │
    │    ▐   ▌           ▌  ▐                               ▌  ▐ │
    │    ▐   ▐           ▌  ▐                               ▌   ▌│
    │▌   ▐   ▐          ▐   ▐                               ▌   ▌│
    │▐   ▌   ▐          ▐    ▌                             ▐    ▌│
    │ ▌  ▌    ▌         ▐    ▌                             ▐    ▐│
    │─▚▄▄▌────▀▙▄▄▄▖────▐────▀▚▄▄▄▄▄▄▄▄▖─────▗▄▄▄▄▄▄▄▄▄▄▄▄▄▟────▝│ 0.0MW
    │              ▌    ▞              ▐     ▌                   │
    │              ▚    ▌              ▐    ▗▘                   │
    │              ▐    ▌              ▐    ▞                    │
    │              ▐   ▗▘              ▝▖   ▌                    │
    │              ▝▖  ▐                ▌  ▗▘                    │
    │               ▌  ▞                ▌  ▐                     │
    │               ▌  ▌                ▚  ▞                     │
    │               ▙▄▄▘                ▐▄▄▌                     │ -0.5MW
    └────────────────────────────────────────────────────────────┘
    06:00         09:00          12:00          15:00
                    ██ discharging (toy-battery)


Here, negative values denote output from the grid, so that's when the battery gets charged.

We can also look at the charging schedule in the `FlexMeasures UI <http://localhost:5000/sensors/2>`_ (reachable via the asset page for the battery):

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-charging.png
    :align: center
|

Recall that we only asked for a 12 hour schedule here. We started our schedule *after* the high price peak (at 4am) and it also had to end *before* the second price peak fully realized (at 8pm).

Our scheduler didn't have many opportunities to optimize, but it found some. This battery can fully charge in around an hour, and therefore, it runs two cycles. For instance, in the second cycle it buys at the lowest price (at 2pm) and sells it off at the highest price within the given 12 hours (at 6pm).

The `battery's graph dashboard <http://localhost:5000/assets/3/graphs>`_ shows both prices and the schedule.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/asset-view-without-solar.png
    :align: center
|

.. note:: The ``flexmeasures add schedule`` command also accepts state-of-charge targets, so the schedule can be more sophisticated.
   But that is not the point of this tutorial.
   See ``flexmeasures add schedule --help`` for available CLI options, :ref:`describing_flexibility` for all flex-model fields or check out the :ref:`tut_v2g` for a tangible example of modelling storage constraints.

This tutorial showed the fastest way to a schedule. In :ref:`tut_toy_schedule_expanded`, we'll go further into settings with more realistic ingredients: solar panels and a limited grid connection.
