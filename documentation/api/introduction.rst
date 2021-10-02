.. _api_introduction:

Introduction
============

This document details the Application Programming Interface (API) of the FlexMeasures web service. The API supports user automation for flexibility valorisation in the energy sector, both in a live setting and for the purpose of simulating scenarios. The web service adheres to the concepts and terminology used in the Universal Smart Energy Framework (USEF).


.. _api_versions:

Main endpoint and API versions
------------------------------

All versions of the API are released on:

.. code-block:: html

    https://<flexmeasures-root-url>/api

So if you are running FlexMeasures on your computer, it would be:

.. code-block:: html

    https://localhost:5000/api

At Seita, we run servers for our clients at:

.. code-block:: html

    https://company.flexmeasures.io/api

where `company` is a hosting customer of ours. All their accounts' data lives on that server.

We assume in this document that the FlexMeasures instance you want to connect to is hosted at https://company.flexmeasures.io.

Let's see what the ``/api`` endpoint returns:

.. code-block:: python

    >>> import requests
    >>> res = requests.get("https://company.flexmeasures.io/api")
    >>> res.json()
    {'flexmeasures_version': '0.4.0',
     'message': 'For these API versions a public endpoint is available, listing its service. For example: /api/v1/getService and /api/v1_1/getService. An authentication token can be requested at: /api/requestAuthToken',
     'status': 200,
     'versions': ['v1', 'v1_1', 'v1_2', 'v1_3', 'v2_0']
    }

So this tells us which API versions exist. For instance, we know that the latest API version is available at

.. code-block:: html

    https://company.flexmeasures.io/api/v2_0


Also, we can see that a list of endpoints which are available at (a version of) the FlexMeasures web service can be obtained by sending a ``getService`` request. An optional field "access" can be used to specify a user role for which to obtain only the relevant services.

**Example request**

Let's ask which endpoints are available for meter data companies (MDC):

.. code-block:: html

    https://company.flexmeasures.io/api/v2_0/getService?access=MDC


**Example response**

.. code-block:: json

    {
        "type": "GetServiceResponse",
        "version": "1.0",
        "services": [
            {
                "name": "getMeterData",
                "access": ["Aggregator", "Supplier", "MDC", "DSO", "Prosumer", "ESCo"],
                "description": "Request meter reading"
            },
            {
                "name": "postMeterData",
                "access": ["MDC"],
                "description": "Send meter reading"
            }
        ]
    }

.. _api_auth:

Authentication
--------------

Service usage is only possible with a user access token specified in the request header, for example:

.. code-block:: json

    {
        "Authorization": "<token>"
    }

A fresh "<token>" can be generated on the user's profile after logging in:

.. code-block:: html

    https://company.flexmeasures.io/logged-in-user

or through a POST request to the following endpoint:

.. code-block:: html

    https://company.flexmeasures.io/api/requestAuthToken

using the following JSON message for the POST request data:

.. code-block:: json

    {
        "email": "<user email>",
        "password": "<user password>"
    }

which gives a response like this if the credentials are correct:

.. code-block:: json

    {
        "auth_token": "<authentication token>",
        "user_id": "<ID of the user>"
    }

.. note:: Each access token has a limited lifetime, see :ref:`auth`.


Roles
-----

We distinguish the following roles with different access rights to the individual services. Capitalised roles are defined by USEF:

- public
- user
- admin
- Aggregator
- Supplier: an energy retailer (see :ref:`supplier`)
- Prosumer: an asset owner (see :ref:`prosumer`)
- ESCo: an energy service company (see :ref:`esco`)
- MDC: a meter data company (see :ref:`mdc`)
- DSO: a distribution system operator (see :ref:`dso`)

.. _sources:

Sources
-------

Requests for data may limit the data selection by specifying a source, for example, a specific user.
USEF roles are also valid source selectors.
For example, to obtain data originating from either a meter data company or user 42, include the following:

.. code-block:: json

    {
        "sources": ["MDC", "42"],
    }

Notation
--------
All requests and responses to and from the web service should be valid JSON messages.

Singular vs plural keys
^^^^^^^^^^^^^^^^^^^^^^^

Throughout this document, keys are written in singular if a single value is listed, and written in plural if multiple values are listed, for example:

.. code-block:: json

    {
        "keyToValue": "this is a single value",
        "keyToValues": ["this is a value", "and this is a second value"]
    }

The API, however, does not distinguish between singular and plural key notation.

Connections and entity addresses
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Connections are end points of the grid at which an asset is located. 
Connections should be identified with an entity address following the EA1 addressing scheme prescribed by USEF[1],
which is mostly taken from IETF RFC 3720 [2]:

This is the complete structure of an EA1 address:

.. code-block:: json

    {
        "connection": "ea1.{date code}.{reversed domain name}:{locally unique string}"
    }

Here is a full example for a FlexMeasures connection address: 

.. code-block:: json

    {
        "connection": "ea1.2021-02.io.flexmeasures.company:fm0.30:73"
    }

where FlexMeasures runs at `company.flexmeasures.io` (which the current domain owner started using in February 2021), and the locally unique string is of scheme `fm0` (see below) and the asset ID is 73. The asset's owner ID is 30, but this part is optional.

Both the owner ID and the asset ID, as well as the full entity address can be obtained on the asset's listing:

.. code-block:: html

    https://company.flexmeasures.io/assets


Entity address structure
""""""""""""""""""""""""""
Some deeper explanations about an entity address:

- "ea1" is a constant, indicating this is a type 1 USEF entity address
- The date code "must be a date during which the naming authority owned the domain name used in this format, and should be the first month in which the domain name was owned by this naming authority at 00:01 GMT of the first day of the month.
- The reversed domain name is taken from the naming authority (person or organization) creating this entity address
- The locally unique string can be used for local purposes, and FlexMeasures uses it to identify the resource.
  Fields in the locally unique string are separated by colons, see for other examples
  IETF RFC 3721, page 6 [3]. While [2] says it's possible to use dashes, dots or colons as separators, we might use dashes and dots in
  latitude/longitude coordinates of sensors, so we settle on colons.


[1] https://www.usef.energy/app/uploads/2020/01/USEF-Flex-Trading-Protocol-Specifications-1.01.pdf

[2] https://tools.ietf.org/html/rfc3720

[3] https://tools.ietf.org/html/rfc3721


Types of asset identifications used in FlexMeasures
""""""""""""""""""""""""""""""""""""""""""""""""""""

FlexMeasures expects the locally unique string string to contain information in
a certain structure. We distinguish type ``fm0`` and type ``fm1`` FlexMeasures entity addresses.

The ``fm0`` scheme is the original scheme. It identifies connected assets, weather stations, markets and UDI events in different ways. 

Examples for the fm0 scheme:

- connection = ea1.2021-01.localhost:fm0.40:30
- connection = ea1.2021-01.io.flexmeasures:fm0.<owner_id>:<asset_id>
- weather_sensor = ea1.2021-01.io.flexmeasures:fm0.temperature:52:73.0
- weather_sensor = ea1.2021-01.io.flexmeasures:fm0.<sensor_type>:<latitude>:<longitude>
- market = ea1.2021-01.io.flexmeasures:fm0.epex_da
- market = ea1.2021-01.io.flexmeasures:fm0.<market_name>
- event = ea1.2021-01.io.flexmeasures:fm0.40:30:302:soc
- event = ea1.2021-01.io.flexmeasures:fm0.<owner_id>:<asset_id>:<event_id>:<event_type>

This scheme is explicit but also a little cumbersome to use, as one needs to look up the type or even owner (for assets), and weather sensors are identified by coordinates.
For the fm0 scheme, the 'fm0.' part is optional, for backwards compatibility.


The ``fm1`` scheme is the latest version, currently under development. It works with the database structure 
we are developing in the background, where all connected sensors have unique IDs. This makes it more straightforward (the scheme works the same way for all types of sensors), if less explicit.

Examples for the fm1 scheme:

- sensor = ea1.2021-01.io.flexmeasures:fm1.42
- sensor = ea1.2021-01.io.flexmeasures:fm1.<sensor_id>
- connection = ea1.2021-01.io.flexmeasures:fm1.<sensor_id>
- market = ea1.2021-01.io.flexmeasures:fm1.<sensor_id>
- weather_station = ea1.2021-01.io.flexmeasures:fm1.<sensor_id>
    
.. todo:: UDI events are not yet modelled in the fm1 scheme, but will probably be ea1.2021-01.io.flexmeasures:fm1.<actuator_id>


Groups
^^^^^^

Data such as measurements, load prognoses and tariffs are usually stated per group of connections.
When the attributes "start", "duration" and "unit" are stated outside of "groups" they are inherited by each of the individual groups. For example:

.. code-block:: json

    {
        "groups": [
            {
                "connections": [
                    "ea1.2021-02.io.flexmeasures.company:fm0.30:71",
                    "ea1.2021-02.io.flexmeasures.company:fm0.30:72"
                ],
                "values": [
                    306.66,
                    306.66,
                    0,
                    0,
                    306.66,
                    306.66
                ]
            },
            {
                "connection": "ea1.2021-02.io.flexmeasures.company:fm0.30:73"
                "values": [
                    306.66,
                    0,
                    0,
                    0,
                    306.66,
                    306.66
                ]
            }
        ],
        "start": "2016-05-01T12:45:00Z",
        "duration": "PT1H30M",
        "unit": "MW"
    }

In case of a single group of connections, the message may be flattened to:

.. code-block:: json

    {
        "connections": [
            "ea1.2021-02.io.flexmeasures.company:fm0.30:71",
            "ea1.2021-02.io.flexmeasures.company:fm0.30:72"
        ],
        "values": [
            306.66,
            306.66,
            0,
            0,
            306.66,
            306.66
        ],
        "start": "2016-05-01T12:45:00Z",
        "duration": "PT1H30M",
        "unit": "MW"
    }

Timeseries
^^^^^^^^^^

Timestamps and durations are consistent with the ISO 8601 standard. The resolution of the data is implicit (from duration and number of values), see :ref:`resolutions`.

All timestamps in requests to the API must be timezone-aware. For instance, in the below example, the timezone indication "Z" indicates a zero offset from UTC.

We use the following shorthand for sending sequential, equidistant values within a time interval:

.. code-block:: json

    {
        "values": [
            10,
            5,
            8
        ],
        "start": "2016-05-01T13:00:00Z",
        "duration": "PT45M"
    }

Technically, this is equal to:

.. code-block:: json

    {
        "timeseries": [
            {
                "value": 10,
                "start": "2016-05-01T13:00:00Z",
                "duration": "PT15M"
            },
            {
                "value": 5,
                "start": "2016-05-01T13:15:00Z",
                "duration": "PT15M"
            },
            {
                "value": 8,
                "start": "2016-05-01T13:30:00Z",
                "duration": "PT15M"
            }
        ]
    }

This intuitive convention allows us to reduce communication by sending univariate timeseries as arrays.

Notation for v1
"""""""""""""""

For version 1 and 2 of the API, only equidistant timeseries data is expected to be communicated. Therefore:

- only the array notation should be used (first notation from above),
- "start" should be a timestamp on the hour or a multiple of the sensor resolution thereafter (e.g. "16:10" works if the resolution is 5 minutes), and
- "duration" should also be a multiple of the sensor resolution.


.. _beliefs:

Tracking the recording time of beliefs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For all its time series data, FlexMeasures keeps track of the time they were recorded. Data can be defined and filtered accordingly, which allows you to get a snapshot of what was known at a certain point in time.

.. note:: FlexMeasures uses the `timely-beliefs data model <https://github.com/SeitaBV/timely-beliefs/#the-data-model>`_ for modelling such facts about time series data, and accordingly we use the term "belief" in this documentation. In that model, the recording time is referred to as "belief time".


Querying by recording time
""""""""""""""""""""""""""""

Some GET endpoints have two optional timing fields to allow such filtering.

The ``prior`` field (a timestamp) can be used to select beliefs recorded before some moment in time.
It can be used to "time-travel" to see the state of information at some moment in the past.

In addition, the ``horizon`` field (a duration) can be used to select beliefs recorded before some moment in time, `relative to each event`.
For example, to filter out meter readings communicated within a day (denoted by a negative horizon) or forecasts created at least a day beforehand (denoted by a positive horizon).

The two timing fields follow the ISO 8601 standard and are interpreted as follows:

- ``prior``: recorded prior to <timestamp>.
- ``horizon``: recorded at least <duration> before the fact (indicated by a positive horizon), or at most <duration> after the fact (indicated by a negative horizon).

For example (note that you can use both fields together):

.. code-block:: json

    {
        "horizon": "PT6H",
        "prior": "2020-08-01T17:00:00Z"
    }

These fields denote that the data should have been recorded at least 6 hours before the fact (i.e. forecasts) and prior to 5 PM on August 1st 2020 (UTC).

.. note:: In addition to these two timing filters, beliefs can be filtered by their source (see :ref:`sources`).


.. _prognoses:

Setting the recording time
""""""""""""""""""""""""""""

Some POST endpoints have two optional fields to allow setting the time at which beliefs are recorded in an explicit manner.
This is useful to keep an accurate history of what was known at what time, especially for prognoses.
If not used, FlexMeasures will infer the belief time from the arrival time of the message.

The "prior" field (a timestamp) can be used to set a single time at which the entire time series (e.g. a prognosed series) was recorded.
Alternatively, the "horizon" field (a duration) can be used to set the recording times relative to each (prognosed) event.
In case both fields are set, the earliest possible recording time is determined and recorded for each (prognosed) event.

The two timing fields follow the ISO 8601 standard and are interpreted as follows:

.. code-block:: json

    {
        "values": [
            10,
            5,
            8
        ],
        "start": "2016-05-01T13:00:00Z",
        "duration": "PT45M",
        "prior": "2016-05-01T07:45:00Z",
    }

This message implies that the entire prognosis was recorded at 7:45 AM UTC, i.e. 6 hours before the end of the entire time interval.

.. code-block:: json

    {
        "values": [
            10,
            5,
            8
        ],
        "start": "2016-05-01T13:00:00Z",
        "duration": "PT45M",
        "horizon": "PT6H"
    }

This message implies that all prognosed values were recorded 6 hours in advance.
That is, the value for 1:00-1:15 PM was made at 7:15 AM, the value for 1:15-1:30 PM was made at 7:30 AM, and the value for 1:30-1:45 PM was made at 7:45 AM.

Negative horizons may also be stated (breaking with the ISO 8601 standard) to indicate a belief about something that has already happened (i.e. after the fact, or simply *ex post*).
For example, the following message implies that all prognosed values were made 10 minutes after the fact:

.. code-block:: json

    {
        "values": [
            10,
            5,
            8
        ],
        "start": "2016-05-01T13:00:00Z",
        "duration": "PT45M",
        "horizon": "-PT10M"
    }

Note that, for a horizon indicating a belief 10 minutes after the *start* of each 15-minute interval, the "horizon" would have been "PT5M".
This denotes that the prognosed interval has 5 minutes left to be concluded.

.. _resolutions:

Resolutions
^^^^^^^^^^^

Specifying a resolution is redundant for POST requests that contain both "values" and a "duration" ― FlexMeasures computes the resolution by dividing the duration by the number of values.

When POSTing data, FlexMeasures checks this computed resolution against the required resolution of the assets which are posted to. If these can't be matched (through upsampling), an error will occur.

GET requests (such as *getMeterData*) return data in the resolution which the sensor is configured for.
A "resolution" may be specified explicitly to obtain the data in downsampled form, 
which can be very beneficial for download speed. The specified resolution needs to be a multiple
of the asset's resolution, e.g. hourly or daily values if the asset's resolution is 15 minutes.

.. _units:

Units
^^^^^

Valid units for timeseries data in version 1 of the API are "MW" only.

.. _signs:

Signs of power values
^^^^^^^^^^^^^^^^^^^^^

USEF recommends to use positive power values to indicate consumption and negative values to indicate production, i.e.
to take the perspective of the Prosumer.
If an asset has been configured as a pure producer or pure consumer, the web service will help avoid mistakes by checking the sign of posted power values.
