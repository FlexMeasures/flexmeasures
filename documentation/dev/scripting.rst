.. _scripting:

Scripting FlexMeasures
========================

Scripting means to write simple Python code so that FlexMeasures gets the data structure you need and will do what you want.

There are two ways: Scripting via the FlexMeasures Client and via the CLI.


Scripting via the FlexMeasures-Client
--------------------------------------

The most universal way to script FlexMeasures is via `the FlexMeasures Client <https://github.com/FlexMeasures/flexmeasures-client/>`_.
Actually, this is scripting via the API, as the client is not much more than a wrapper around the FlexMeasures server API.

Let's look at two examples, to give an impression. The first one creates an asset:

.. code-block:: python

    # Create energy costs KPI sensor (1D resolution, EUR)
    energy_costs_sensor = await client.add_sensor(
        name="energy-costs-kpi",
        event_resolution="P1D",
        unit="EUR",
        generic_asset_id=site_asset["id"],
        timezone="Europe/Amsterdam",
    )

The second one triggers a schedule and polls until it is ready:

.. code-block:: python

    schedule = await flexmeasures_client.trigger_and_get_schedule(
        asset_id=<asset_id>,  # the asset ID (int) of the asset that all relevant power sensors belong to (or live under, in case of a tree-like asset structure)
        start="2023-03-26T10:00+02:00",  # ISO datetime
        duration="PT12H",  # ISO duration
        flex-model=[
            # Example flex-model for an electric truck at a regular Charge Point
            {
                "sensor": <power_sensor_id>,  # int
                "soc-at-start": "50 kWh",
                "soc-targets": [
                    {"value": "100 kWh", "datetime": "2023-03-03T11:00+02:00"},
                ],
            },
            # Example flex-model for curtailable solar panels
            {
                "sensor": <another_power_sensor_id>,  # int
                "power-capacity": "20 kVA",
                "consumption-capacity": "0 kW",
                "production-capacity": {"sensor": <another_power_sensor_id>},  # int
            },
        ],
    )

To illustrate how far scripting with the client can go, we made an example where a whole simulation of a building with both EVs and heat pump is ran for a few days. 

.. figure:: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/HEMS-tutorial-dashboard.png 
    :target: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/HEMS-tutorial-dashboard.png
    :align: center

    The resulting dashboard of a completely scripted HEMS system


This example ...

- creates the whole structure - with PV, battery and a heat pump.
- loads two weeks of historical data and creates forecasts through the forecasting API.
- goes through one week in 4h steps, forecasting and scheduling all flexible assets.

You can dive into the code `here <https://github.com/FlexMeasures/flexmeasures-client/blob/main/examples/HEMS/HEMS_setup.py>`_.


We believe the client code is also a very good way to create small, reproducible examples. That can be quote productive to share small setups between teams or on Github for troubleshooting.


Scripting via the CLI
---------------------

Scripting via the CLI is not vor everyone - only if you are hosting FlexMeasures, can you run such scripts.
It is also just Python code, but you need to be on the server to use them.

A good example might be that the construction of the toy account (for use in the toy tutorials) is scripted via the CLI, see the command ``flexmeasures add toy-account``.

We wrote a reasonably large library of :ref:`cli`. You can use them easily in Bash scripting. They do, however, take a bit of time to execute, as they first load the Flask app context. The client is faster.

Some features that are not on the API (like, at the time of writing, account creation) would only work via the CLI.

If you are developing your own plugin, you can freely write your own CLI commands.
