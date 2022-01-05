.. _tut_posting_data:

Posting data
============

The platform FlexMeasures strives on the data you feed it. Let's demonstrate how you can get data into FlexMeasures using the API. This is where FlexMeasures gets connected to your system as a smart backend and helps you build smart energy services.

We will show how to use the API endpoints for POSTing data.
You can call these at regular intervals (through scheduled scripts in your system, for example), so that FlexMeasures always has recent data to work with.
Of course, these endpoints can also be used to load historic data into FlexMeasures, so that the forecasting models have access to enough data history.

.. note:: For the purposes of forecasting and scheduling, it is often advisable to use a less fine-grained resolution than most metering services keep. For example, while such services might measure every ten seconds, FlexMeasures will usually do its job no less effective if you feed it data with a resolution of five minutes. This will also make the data integration much easier. Keep in mind that many data sources like weather forecasting or markets can have data resolutions of an hour, anyway.

.. contents:: Table of contents
    :local:
    :depth: 1

Prerequisites
--------------

- FlexMeasures needs some structural meta data for data to be understood. For example, for adding weather data we need to define a weather sensor, and what kind of weather sensors there are. You also need a user account. If you host FlexMeasures yourself, you need to add this info first. Head over to :ref:`getting_started`, where these steps are covered, or study our :ref:`cli`.
- You should be familiar with where to find your API endpoints (see :ref:`api_versions`) and how to authenticate against the API (see :ref:`api_auth`).

.. note:: For deeper explanations of the data and the meta fields we'll send here, You can always read the :ref:`api_introduction` , e.g. :ref:`signs`, :ref:`resolutions`, :ref:`prognoses` and :ref:`units`.

.. note:: To address assets and sensors, these tutorials assume entity addresses valid in the namespace ``fm0``. See :ref:`api_introduction` for more explanations. 


Posting weather data
--------------------

Weather data (both observations and forecasts) can be posted to `POST  /api/v2_0/postWeatherData <../api/v2_0.html#post--api-v2_0-postWeatherData>`_. The URL might look like this:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/postWeatherData

Weather data can be posted for different types of sensors, such as:

- "radiation" (with kW/m² as unit)
- "temperature" (with °C as unit)
- "wind speed" (with m/s as unit)

The sensor type is part of the unique entity address for each sensor, together with the sensor's latitude and longitude.

This "PostWeatherDataRequest" message posts temperature forecasts for 15-minute intervals between 3.00pm and 4.30pm for a weather sensor with id 602.
As this sensor is located in Korea's timezone ― we also reflect that in the datetimes.
The forecasts were made at noon, as the ``prior`` field indicates.

.. code-block:: json

        {
            "type": "PostWeatherDataRequest",
            "sensor": "ea1.2021-01.io.flexmeasures.company:fm1.602",
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

Note how the resolution of the data comes out at 15 minutes when you divide the duration by the number of data points.
If this resolution does not match the sensor's resolution, FlexMeasures will try to upsample the data to make the match or, if that is not possible, complain.


Observations vs forecasts
^^^^^^^^^^^^^^^^^^^^^^^^^

To post an observation rather than a forecast, simply set the prior to the moment at which the observations were made, e.g. at "2015-01-01T16:30:00+09:00".
This denotes that the observation was made exactly after realisation of this list of temperature readings, i.e. at 4.30pm.

Alternatively, to indicate that each individual observation was made directly after the end of its 15-minute interval (i.e. at 3.15pm, 3.30pm and so on), set a horizon to "PT0H" instead of a prior.

Finally, delays in reading out sensor data can be simulated by setting the horizon field to a negative value.
For example, a horizon of "-PT1H" would denote that each temperature reading was observed one hour after the fact (i.e. at 4.15pm, 4.30pm and so on).

See :ref:`prognoses` for more information regarding the prior and horizon fields.


Collecting weather data from OpenWeatherMap
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For convenience for organisations who host FlexMeasures themselves, we built in a CLI task which collects weather measurements and forecasts from the OpenWeatherMap API.
You have to add your own token in the OPENWEATHERMAP_API_KEY setting first. Then you could run this task periodically, probably once per hour. Here is how:

.. code-block::

   flexmeasures add external-weather-forecasts --location 33.4366,126.5269 --store-in-db

Consult the ``--help`` for this command to learn more about what you can do with it.


Posting price data
------------------

Price data (both observations and forecasts) can be posted to `POST  /api/v2_0/postPriceData <../api/v2_0.html#post--api-v2_0-postPriceData>`_. The URL might look like this:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/postPriceData

This example "PostPriceDataRequest" message posts prices for hourly intervals between midnight and midnight the next day
for the Korean Power Exchange (KPX) day-ahead auction, registered under sensor 16.
The ``prior`` indicates that the prices were published at 3pm on December 31st 2014 (i.e. the clearing time of the KPX day-ahead market, which is at 3 PM on the previous day ― see below for a deeper explanation).

.. code-block:: json

    {
        "type": "PostPriceDataRequest",
        "market": "ea1.2021-01.io.flexmeasures.company:fm1.16",
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
        "start": "2015-01-01T00:00:00+09:00",
        "duration": "PT24H",
        "prior": "2014-12-03T15:00:00+09:00",
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
Observations of power data can be posted to `POST /api/v2_0/postMeterData <../api/v2_0.html#post--api-v2_0-postMeterData>`_. The URL might look like this:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/postMeterData

while forecasts of power data can be posted to `POST /api/v2_0/postPrognosis <../api/v2_0.html#post--api-v2_0-postPrognosis>`_. The URL might look like this:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/postPrognosis

For both endpoints, power data can be posted in various ways.
The following examples assume that the endpoint for power data observations (i.e. meter data) is used.

.. todo:: For the time being, only one rate unit (MW) can be used to post power values.


Single value, single connection
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A single average power value for a 15-minute time interval for a single connection, posted 5 minutes after realisation.

.. code-block:: json

    {
        "type": "PostMeterDataRequest",
        "connection": "ea1.2021-01.io.flexmeasures.company:fm1.1",
        "value": 220,
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT0H15M",
        "horizon": "-PT5M",
        "unit": "MW"
    }

Multiple values, single connection
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Multiple values (indicating a univariate timeseries) for 15-minute time intervals for a single connection, posted 5 minutes after each realisation.

.. code-block:: json

    {
        "type": "PostMeterDataRequest",
        "connection": "ea1.2021-01.io.flexmeasures.company:fm1.1",
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
            "ea1.2021-01.io.flexmeasures.company:fm1.1",
            "ea1.2021-01.io.flexmeasures.company:fm1.2"
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
                "connection": "ea1.2021-01.io.flexmeasures.company:fm1.1",
                "value": 220
            },
            {
                "connection": "ea1.2021-01.io.flexmeasures.company:fm1.2",
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

Multiple values (indicating a univariate timeseries) for 15-minute time intervals for two connections, posted 5 minutes after each realisation.

.. code-block:: json

    {
        "type": "PostMeterDataRequest",
        "groups": [
            {
                "connection": "ea1.2021-01.io.flexmeasures.company:fm1.1",
                "values": [
                    220,
                    210,
                    200
                ]
            },
            {
                "connection": "ea1.2021-01.io.flexmeasures.company:fm1.2",
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


.. _posting_flex_states:

Posting flexibility states
-------------------------------

There is one more crucial kind of data that FlexMeasures needs to know about: What are the current states of flexible devices? For example, a battery has a state of charge.

The USEF framework defines a so-called "UDI-Event" (UDI stands for Universal Device Interface) to communicate settings for devices with Active Demand & Supply (ADS).
Owners of such devices can post these states to `POST /api/v2_0/postUdiEvent <../api/v2_0.html#post--api-v2_0-postUdiEvent>`_. The URL might look like this:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/postUdiEvent

This example posts a state of charge value for a battery device (asset 10 of owner 7) as UDI event 203.
From this, FlexMeasures derives the energy flexibility this battery has in the near future.

.. code-block:: json

        {
            "type": "PostUdiEventRequest",
            "event": "ea1.2021-01.io.flexmeasures.company:7:10:203:soc",
            "value": 12.1,
            "datetime": "2015-06-02T10:00:00+00:00",
            "unit": "kWh"
        }

.. note:: At the moment, FlexMeasures only supports batteries and car chargers here (asset types "battery", "one-way_evse" or "two-way_evse").
          This will be expanded to flexible assets as needed.

Actually, UDI Events are more powerful than this. In :ref:`how_queue_scheduling`, we'll cover how they can be used to request a future state, which is useful to steer the scheduling.