.. _simulation:

Simulation
==========

This document details examples for using a FlexMeasures server for simulation.
The API on a server that is set up for simulation is extended with several features that make it possible to run simulations of energy flows and control actions.
Please read the :ref:`api_introduction` for explanations of the message fields, specifically regarding:

- The sign of values (:ref:`signs`)
- Valid durations (:ref:`resolutions`)
- Valid horizons (:ref:`prognoses`)
- Valid units (:ref:`simulation`)

.. contents:: Table of contents
    :local:
    :depth: 1

Setting up
----------

Researchers require an admin account to set up a new simulation with a number of assets.

Creating assets and owners
^^^^^^^^^^^^^^^^^^^^^^^^^^

New assets can be created through the UI on:

.. code-block:: html

    https://company.flexmeasures.io/assets/new


We recommend that researchers choose their own admin account as the asset's owner.
This way, the simulation will only require refreshing of the access token for the admin account.
Alternatively, researchers can set up unique accounts for each agent in a multi-agent simulation by creating new owners.
In this case, access tokens need to be refreshed by each agent separately.

Authentication
^^^^^^^^^^^^^^

Service usage is only possible with a user authentication token specified in the request header, for example:

.. code-block:: json

    {
        "Authorization": "<token>"
    }

The "<token>" can be obtained on your profile after logging in:

.. code-block:: html

    https://company.flexmeasures.io/account

For security reasons, tokens expire after a certain amount of time (see :ref:`_auth`).
To automate token renewal, use the following POST endpoint:

.. code-block:: html

    https://company.flexmeasures.io/api/requestAuthToken

Providing applicable user credentials:

.. code-block:: json

        {
            "email": "<email>",
            "password": "<password>"
        }

Posting weather data
--------------------

Weather data (both observations and forecasts) can be posted to the following POST endpoint:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/postWeatherData

Weather data can be posted for the following three types of weather sensors:

- "radiation" (with kW/m² as unit)
- "temperature" (with °C as unit)
- "wind_speed" (with m/s as unit)

The sensor type is part of the unique entity address for each sensor, together with the sensor's latitude and longitude.

This "PostWeatherDataRequest" message posts temperature forecasts for 15-minute intervals between 3.00pm and 4.30pm for a weather sensor located at latitude 33.4843866 and longitude 126.477859.
The forecasts were made at noon.

.. code-block:: json

        {
            "type": "PostWeatherDataRequest",
            "sensor": "ea1.2018-06.io.flexmeasures.company:temperature:33.4843866:126.477859",
            "values": [
                20.04,
                20.23,
                20.41,
                20.51,
                20.55,
                20.57
            ],
            "start": "2015-01-01T15:00:00+09:00",
            "duration": "PT1H30M",
            "prior": "2015-01-01T12:00:00+09:00",
            "unit": "°C"
        }

Observations vs forecasts
^^^^^^^^^^^^^^^^^^^^^^^^^

To post an observation rather than a forecast, simply set the prior to the moment at which the observations were made, e.g. at "2015-01-01T16:30:00+09:00".
This denotes that the observation was made exactly after realisation of this list of temperature readings, i.e. at 4.30pm.

Alternatively, to indicate that each individual observation was made directly after the end of its 15-minute interval (i.e. at 3.15pm, 3.30pm and so on), set a horizon to "PT0H" instead of a prior.

Finally, delays in reading out sensor data can be simulated by setting the horizon field to a negative value.
For example, a horizon of "-PT1H" would denote that each temperature reading was observed one hour after the fact (i.e. at 4.15pm, 4.30 pm and so on).

See :ref:`prognoses` for more information regarding the prior and horizon fields.


Posting price data
------------------

Price data (both observations and forecasts) can be posted to the following POST endpoint:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/postPriceData

This example "PostPriceDataRequest" message posts prices for hourly intervals between midnight and midnight the next day
for the Korean Power Exchange (KPX) day-ahead auction.
The horizon indicates that the prices were published at 3pm on December 31st 2014
(i.e. 33 hours ahead of midnight the next day).

.. code-block:: json

    {
        "type": "PostPriceDataRequest",
        "market": "ea1.2018-06.io.flexmeasures.company:kpx_da",
        "values": [
            52.37,
            51.14,
            49.09,
            48.35,
            48.47,
            49.98,
            58.7,
            67.76,
            69.21,
            70.26,
            70.46,
            70,
            70.7,
            70.41,
            70,
            64.53,
            65.92,
            69.72,
            70.51,
            75.49,
            70.35,
            70.01,
            66.98,
            58.61
        ],
        "start": "2015-01-01T15:00:00+09:00",
        "duration": "PT24H",
        "horizon": "PT33H",
        "unit": "KRW/kWh"
    }

Observations vs forecasts
^^^^^^^^^^^^^^^^^^^^^^^^^

For markets, the time at which the market is cleared (i.e. when contracts are signed) determines the difference between an ex-post observation and an ex-ante forecast.
For example, at the KPX day-ahead auction this is every day at 3pm.
To post a forecast rather than an observation, simply increase the horizon.
For example, a horizon of "PT57H" would denote a forecast of 24 hours ahead of clearing.


Posting power data
------------------

For power data, USEF specifies separate message types for observations and forecasts.
Correspondingly, FlexMeasures uses separate endpoints to communicate these messages.
Observations of power data can be posted to the following POST endpoint:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/postMeterData

while forecasts of power data can be posted to the following POST endpoint:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/postPrognosis

For both endpoints, power data can be posted in various ways.
The following examples assume that the endpoint for power data observations (i.e. meter data) is used.


Single value, single connection
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A single average power value for a 15-minute time interval for a single connection, posted 5 minutes after realisation.

.. code-block:: json

    {
        "type": "PostMeterDataRequest",
        "connection": "ea1.2018-06.io.flexmeasures.company:1:1",
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
        "connection": "ea1.2018-06.io.flexmeasures.company:1:1",
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
            "ea1.2018-06.io.flexmeasures.company:1:1",
            "ea1.2018-06.io.flexmeasures.company:1:2"
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
                "connection": "ea1.2018-06.io.flexmeasures.company:1:1",
                "value": 220
            },
            {
                "connection": "ea1.2018-06.io.flexmeasures.company:1:2",
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
                "connection": "ea1.2018-06.io.flexmeasures.company:1:1",
                "values": [
                    220,
                    210,
                    200
                ]
            },
            {
                "connection": "ea1.2018-06.io.flexmeasures.company:1:2",
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

Prognoses are power forecasts that are used by FlexMeasures to determine the best control signals to valorise on
balancing opportunities. Researchers can check the accuracy of these forecasts by downloading the prognoses and
comparing them against the meter data, i.e. the realised power measurements.
A prognosis can be requested for a single asset at the following GET endpoint:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/getPrognosis

This example requests a prognosis with a rolling horizon of 6 hours before realisation.

.. code-block:: json

    {
        "type": "GetPrognosisRequest",
        "connection": "ea1.2018-06.io.flexmeasures.company:1:1",
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT24H",
        "horizon": "PT6H",
        "resolution": "PT15M",
        "unit": "MW"
    }

Posting flexibility constraints
-------------------------------

Prosumers that have Active Demand & Supply can post the constraints of their flexible devices to FlexMeasures at the
following POST endpoint:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/postUdiEvent

This example posts a state of charge value for a battery device (asset 10 of owner 7) as UDI event 203.

.. code-block:: json

        {
            "type": "PostUdiEventRequest",
            "event": "ea1.2018-06.io.flexmeasures.company:7:10:203:soc",
            "value": 12.1,
            "datetime": "2015-06-02T10:00:00+00:00",
            "unit": "kWh"
        }

Some devices also accept target values for their state of charge.
As an example, consider the same UDI event as above with an additional target value.

.. code-block:: json

    {
        "type": "PostUdiEventRequest",
        "event": "ea1.2018-06.io.flexmeasures.company:7:10:204:soc-with-targets",
        "value": 12.1,
        "datetime": "2015-06-02T10:00:00+00:00",
        "unit": "kWh",
        "targets": [
            {
                "value": 25,
                "datetime": "2015-06-02T16:00:00+00:00"
            }
        ]
    }

Getting control signals
-----------------------

A Prosumer can query FlexMeasures for control signals for its flexible devices using the following GET endpoint:


.. code-block:: html

    https://company.flexmeasures.io/api/<version>/getDeviceMessage

Control signals can be queried by UDI event for up to 1 week after the UDI event was posted.
This example requests a control signal for UDI event 203 posted previously.

.. code-block:: json

        {
            "type": "GetDeviceMessageRequest",
            "event": "ea1.2018-06.io.flexmeasures.company:7:10:203:soc"
        }

The following example response indicates that FlexMeasures planned ahead 45 minutes.
The list of consecutive power values represents the target consumption of the battery (negative values for production).
Each value represents the average power over a 15 minute time interval.

.. sourcecode:: json

        {
            "type": "GetDeviceMessageResponse",
            "event": "ea1.2018-06.io.flexmeasures.company:7:10:203",
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

All power, price and weather data on the simulation server can be cleared using the following PUT endpoint (admin rights are required):

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/restoreData

This example restores the database to a backup named demo_v0, which contains no timeseries data.

.. code-block:: json

    {
        "backup": "demo_v0"
    }
