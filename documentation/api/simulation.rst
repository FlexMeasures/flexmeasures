.. _simulation:

Simulation
==========

This document details examples for using the BVP **play** server for simulation.
The API on this server is extended with several features that make it possible to run simulations of energy flows and balancing valorisation.
Please read the :ref:`introduction` for explanations of the message fields, specifically regarding:

- The sign of values (:ref:`signs`)
- Valid durations (:ref:`resolutions`)
- Valid horizons (:ref:`prognoses`)
- Valid units (:ref:`units`)

Setting up
----------

Researchers require an admin account to set up a new simulation with a number of assets.

Creating assets and owners
^^^^^^^^^^^^^^^^^^^^^^^^^^

New assets can be created through the UI on:

.. code-block:: html

    https://play.a1-bvp.com/assets/new


We recommend that researchers choose their own admin account as the asset's owner.
This way, the simulation will require only a single access token.
Alternatively, researchers can set up unique accounts for each agent in a multi-agent simulation by creating new owners.

Authentication
^^^^^^^^^^^^^^

Service usage is only possible with a user authentication token specified in the request header, for example:

.. code-block:: json

    {
        "Authorization": "<token>"
    }

The "<token>" can be obtained on your profile after logging in:

.. code-block:: html

    https://play.a1-bvp.com/account


Posting meter data
------------------

Meter data can be posted in various ways to the following POST endpoint:

.. code-block:: html

    https://play.a1-bvp.com/api/<version>/postMeterData


Single value, single connection
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A single average power value for a 15-minute time interval for a single connection, posted 5 minutes after realisation.

.. code-block:: json

    {
        "type": "PostMeterDataRequest",
        "connection": "ea1.2018-06.com.a1-bvp.play:1:1",
        "value": 220,
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT0H15M",
        "horizon": "-PT5M",
        "unit": "MW"
    }

Multiple values, single connection
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Multiple values (indicating a univariate timeseries) for 15-minute time intervals for a single connection, posted 5 minutes after realisation.

.. code-block:: json

    {
        "type": "PostMeterDataRequest",
        "connection": "ea1.2018-06.com.a1-bvp.play:1:1",
        "values": [
            220,
            210,
            200
        ],
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT0H45M",
        "horizon": "-PT5M",
        "unit": "MW"
    }

Single identical value, multiple connections
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Single identical value for a 15-minute time interval for two connections, posted 5 minutes after realisation.
Please note that both connections consumed at 10 MW, i.e. the value does not represent the total of the two connections.
We recommend to use this notation for zero values only.

.. code-block:: json

    {
        "type": "PostMeterDataRequest",
        "connections": [
            "ea1.2018-06.com.a1-bvp.play:1:1",
            "ea1.2018-06.com.a1-bvp.play:1:2"
        ],
        "value": 10,
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT0H15M",
        "horizon": "-PT5M",
        "unit": "MW"
    }

Single different values, multiple connections
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Single different values for a 15-minute time interval for two connections, posted 5 minutes after realisation.

.. code-block:: json

    {
        "type": "PostMeterDataRequest",
        "groups": [
            {
                "connection": "ea1.2018-06.com.a1-bvp.play:1:1",
                "value": 220
            },
            {
                "connection": "ea1.2018-06.com.a1-bvp.play:1:2",
                "value": 300
            }
        ],
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT0H15M",
        "horizon": "-PT5M",
        "unit": "MW"
    }

Multiple values, multiple connections
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Multiple values (indicating a univariate timeseries) for 15-minute time intervals for two connections, posted 5 minutes after realisation.

.. code-block:: json

    {
        "type": "PostMeterDataRequest",
        "groups": [
            {
                "connection": "ea1.2018-06.com.a1-bvp.play:1:1",
                "values": [
                    220,
                    210,
                    200
                ]
            },
            {
                "connection": "ea1.2018-06.com.a1-bvp.play:1:2",
                "values": [
                    300,
                    303,
                    306
                ]
            }
        ],
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT0H45M",
        "horizon": "-PT5M",
        "unit": "MW"
    }

Getting prognoses
-----------------

Prognoses are power forecasts that are used by the BVP server to determine the best control signals to valorise on
balancing opportunities. Researchers can check the accuracy of these forecasts by downloading the prognoses and
comparing them against the meter data, i.e. the realised power measurements.
A prognosis can be requested for a single asset at the following GET endpoint:

.. code-block:: html

    https://play.a1-bvp.com/api/<version>/getPrognosis

This example requests a prognosis with a rolling horizon of 6 hours before realisation.

.. code-block:: json

    {
        "type": "GetPrognosisRequest",
        "connection": "ea1.2018-06.com.a1-bvp.play:1:1",
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT24H",
        "horizon": "R/PT6H",
        "resolution": "PT15M",
        "unit": "MW"
    }

Posting flexibility constraints
-------------------------------

Prosumers that have Active Demand & Supply can post the constraints of their flexible devices to the BVP at the
following POST endpoint:

.. code-block:: html

    https://play.a1-bvp.com/api/<version>/postUdiEvent

This example posts a state of charge value for a battery device (asset 10 of owner 7) as UDI event 203.

.. code-block:: json

        {
            "type": "PostUdiEventRequest",
            "event": "ea1.2018-06.com.a1-bvp.play:7:10:203",
            "type": "soc",
            "value": 12.1,
            "datetime": "2015-06-02T10:00:00+00:00",
            "unit": "kWh"
        }

Getting control signals
-----------------------

A Prosumer can query the BVP for control signals for its flexible devices using the following GET endpoint:


.. code-block:: html

    https://play.a1-bvp.com/api/<version>/getDeviceMessage

This example requests a control signal for UDI event 203 posted previously.

.. code-block:: json

        {
            "type": "GetDeviceMessageRequest",
            "event": "ea1.2018-06.com.a1-bvp.play:7:10:203"
        }

The following example response indicates that the BVP planned ahead 45 minutes.
The list of consecutive power values represents the target consumption of the battery (negative values for production).
Each value represents the average power over a 15 minute time interval.

.. sourcecode:: json

        {
            "type": "GetDeviceMessageResponse",
            "event": "ea1.2018-06.com.a1-bvp.play:7:10:203",
            "values": [
                2.15,
                3,
                2
            ],
            "start": "2015-06-02T10:00:00+00:00",
            "duration": "PT45M",
            "unit": "MW"
        }

One way of reaching the target consumption in this example is to let the battery start to consume with 2.15 MW at 10am,
increase its consumption to 3 MW at 10.15am and decrease its consumption to 2 MW at 10.30am.
However, because the targets values represent averages over 15-minute time intervals, the battery still has some degrees of freedom.
For example, the battery might start to consume with 2.1 MW at 10.00am and increase its consumption to 2.25 at 10.10am,
increase its consumption to 5 MW at 10.15am and decrease its consumption to 2 MW at 10.20am.
That should result in the same average values for each quarter-hour.

Resetting the server
--------------------

All power, price and weather data on the play server can be cleared using the following PUT endpoint (admin rights required):

.. code-block:: html

    https://play.a1-bvp.com/api/<version>/restoreData

This example restores the database to a backup named demo_v0, which contains no timeseries data.

.. code-block:: json

    {
        "backup": "demo_v0"
    }
