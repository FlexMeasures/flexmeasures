.. _api_introduction:

Introduction
============

This document details the Application Programming Interface (API) of the FlexMeasures web service. The API supports user automation for flexibility valorisation in the energy sector, both in a live setting and for the purpose of simulating scenarios. The web service adheres to the concepts and terminology used in the Universal Smart Energy Framework (USEF).
We assume in this document that the FlexMeasures instance you want to connect to is hosted at https://company.flexmeasures.io.


New versions of the API are released on:

.. code-block:: html

    https://company.flexmeasures.io/api

A list of services offered by (a version of) the FlexMeasures web service can be obtained by sending a *getService* request. An optional field "access" can be used to specify a user role for which to obtain only the relevant services.

**Example request**

.. code-block:: json

    {
        "type": "GetServiceRequest",
        "version": "1.0"
    }

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

Authentication
--------------

Service usage is only possible with a user access token specified in the request header, for example:

.. code-block:: json

    {
        "Authorization": "<token>"
    }

A fresh "<token>" can be generated on the user's profile after logging in:

.. code-block:: html

    https://company.flexmeasures.io/account

or through a POST request to the following endpoint:

.. code-block:: html

    https://company.flexmeasures.io/api/requestAuthToken

using the following JSON message for the POST request data:

.. code-block:: json

    {
        "email": "<user email>",
        "password": "<user password>"
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

Connections
^^^^^^^^^^^

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
        "connection": "ea1.2021-02.io.flexmeasures.company:30:73"
    }

where FlexMeasures runs at `company.flexmeasures.io` and the owner ID is 30 and the asset ID is 73.
The owner ID is optional. Both the owner ID and the asset ID, as well as the full entity address can be obtained on the asset's listing after logging in:

.. code-block:: html

    https://company.flexmeasures.io/assets


Some deeper explanations about an entity address:

- "ea1" is a constant, indicating this is a type 1 USEF entity address
- The date code "must be a date during which the naming authority owned the domain name used in this format, and should be the first month in which the domain name was owned by this naming authority at 00:01 GMT of the first day of the month.
- The reversed domain name is taken from the naming authority (person or organization) creating this entity address
- The locally unique string can be used for local purposes, and FlexMeasures uses it to identify the resource (more information in parse_entity_address).

[1] https://www.usef.energy/app/uploads/2020/01/USEF-Flex-Trading-Protocol-Specifications-1.01.pdf

[2] https://tools.ietf.org/html/rfc3720


Notation for simulation
"""""""""""""""""""""""

For version 1 of the API, the following simplified addressing scheme may be used:

.. code-block:: json

    {
        "connection": "<owner-id>:<asset-id>"
    }

or even simpler:

.. code-block:: json

    {
        "connection": "<asset-id>"
    }

Groups
^^^^^^

Data such as measurements, load prognoses and tariffs are usually stated per group of connections.
When the attributes "start", "duration" and "unit" are stated outside of "groups" they are inherited by each of the individual groups. For example:

.. code-block:: json

    {
        "groups": [
            {
                "connections": [
                    "CS 1",
                    "CS 2"
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
                "connection": "CS 3",
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
            "CS 1",
            "CS 2"
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

Timestamps and durations are consistent with the ISO 8601 standard. The resolution of the data is implicit, see :ref:`resolutions`.

All timestamps in requests to the API must be timezone-aware. The timezone indication "Z" indicates a zero offset from UTC. Additionally, we use the following shorthand for sequential values within a time interval:

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

is equal to:

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

For version 1 of the API, only univariate timeseries data is expected to be communicated. Therefore:

- only the array notation should be used,
- "start" should be a timestamp on the hour or a multiple of 15 minutes thereafter, and
- "duration" should be a multiple of 15 minutes.

.. _beliefs:

Beliefs
^^^^^^^

By regarding all time series data as beliefs that have been recorded at a certain time, data can be filtered accordingly.
Some GET endpoints have two optional timing fields to allow such filtering.
The "prior" field (a timestamp) can be used to select beliefs recorded before some moment in time.
It can be used to "time-travel" to see the state of information at some moment in the past.
In addition, the "horizon" field (a duration) can be used to select beliefs recorded before some moment in time, relative to each event.
For example, to filter out meter readings communicated within a day (denoted by a negative horizon) or forecasts created at least a day beforehand (denoted by a positive horizon).
In addition to these two timing filters, beliefs can be filtered by their source (see :ref:`sources`).

The two timing fields follow the ISO 8601 standard and are interpreted as follows:

- "horizon": recorded at least <duration> before the fact (indicated by a positive horizon), or at most <duration> after the fact (indicated by a negative horizon).
- "prior": recorded prior to <timestamp>.

For example:

.. code-block:: json

    {
        "horizon": "PT6H",
        "prior": "2020-08-01T17:00:00Z"
    }

These fields denote that the data should have been recorded at least 6 hours before the fact (i.e. forecasts) and prior to 5 PM on August 1st 2020 (UTC).

.. _prognoses:

Prognoses
^^^^^^^^^

Some POST endpoints have two optional fields to allow setting the time at which beliefs are recorded explicitly.
This is useful to keep an accurate history of what was known at what time, especially for prognoses.
If not used, FlexMeasures will infer the prior from the arrival time of the message.

The "prior" field (a timestamp) can be used to set a single time at which the entire prognosis was recorded.
Alternatively, the "horizon" field (a duration) can be used to set the recording times relative to each prognosed event.
In case both fields are set, the earliest possible recording time is determined and recorded for each prognosed event.

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

Negative horizons may also be stated (breaking with the ISO 8601 standard) to indicate a prognosis about something that has already happened (i.e. after the fact, or simply *ex post*).
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

Note that, for a horizon indicating a prognosis 10 minutes after the *start* of each 15-minute interval, the "horizon" would have been "PT5M".
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

Signs
^^^^^

USEF recommends to use positive power values to indicate consumption and negative values to indicate production, i.e.
to take the perspective of the Prosumer.
If an asset has been configured as a pure producer or pure consumer, the web service will help avoid mistakes by checking the sign of posted power values.
