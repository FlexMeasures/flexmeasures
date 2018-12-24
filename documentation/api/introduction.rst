.. _api_introduction:

Introduction
============

This document details the Application Programming Interface (API) of the BVP web service. The API supports user automation for balancing valorisation in the energy sector, both in a live setting and for the purpose of simulating scenarios. The web service adheres to the concepts and terminology used in the Universal Smart Energy Framework (USEF).

New versions of the API are released on:

.. code-block:: html

    https://a1-bvp.com/api

A list of services offered by (a version of) the BVP web service can be obtained by sending a *getService* request. An optional parameter "access" can be used to specify a user role for which to obtain only the relevant services.

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

Service usage is only possible with a user authentication token specified in the request header, for example:

.. code-block:: json

    {
        "Authorization": "<token>"
    }

The "<token>" can be obtained on the user's profile after logging in:

.. code-block:: html

    https://a1-bvp.com/account

or through a POST request to the following endpoint:

.. code-block:: html

    https://a1-bvp.com/api/requestAuthToken

using the following JSON message for the POST request data:

.. code-block:: json

    {
        "email": "<user email>",
        "password": "<user password>"
    }

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

Connections are end points of the grid at which an asset is located. Connections should be identified with an entity address following the EA1 addressing scheme prescribed by USEF. For example:

.. code-block:: json

    {
        "connection": "ea1.2018-06.com.a1-bvp:<owner-id>:<asset-id>"
    }

The "<owner-id>" and "<asset-id>" as well as the full entity address can be obtained on the asset's listing after logging in:

.. code-block:: html

    https://a1-bvp.com/assets

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

Timestamps and durations are consistent with the ISO 8601 standard. All timestamps in requests to the API must be timezone aware. The timezone indication "Z" indicates a zero offset from UTC. Additionally, we use the following shorthand for sequential values within a time interval:

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

.. _prognoses:

Prognoses
^^^^^^^^^

A prognosis should state a time horizon, i.e. the duration between the time at which the prognosis was made and the time of realisation (at the end of a time interval). The horizon can be stated explicitly by including a "horizon", consistent with the ISO 8601 standard, as follows:

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

This message implies that the entire prognosis was made at 7:45 AM UTC, i.e. 6 hours before the end of the time interval.
Alternatively, a rolling horizon can be stated as an ISO 8601 repeating time interval:

.. code-block:: json

    {
        "values": [
            10,
            5,
            8
        ],
        "start": "2016-05-01T13:00:00Z",
        "duration": "PT45M",
        "horizon": "R/PT6H"
    }

Here, the number of repetitions and the repeat rule is omitted as it is implied by our notation for univariate timeseries (a complete representation of the "horizon" would have been "R3/PT6H/FREQ=MI;INTR=15").
This message implies that the value for 1:00-1:15 PM was made at 7:15 AM, the value for 1:15-1:30 PM was made at 7:30 AM, and the value for 1:30-1:45 PM was made at 7:45 AM.

A "horizon" may be omitted, in which case the web service will infer the horizon from the arrival time of the message. Negative horizons may also be stated (breaking with the ISO 8601 standard) to indicate a prognosis about something that has already happened (i.e. after the fact, or simply *ex post*). For example, the following message implies that the entire prognosis was made at 1:55 PM UTC, 10 minutes after the fact:

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

For a rolling horizon indicating a prognosis 10 minutes after the start of each 15-minute interval, the "horizon" would have been "R/PT5M" since in fact only the last 5 minutes of each interval occurs before the fact (*ex ante*).
That is, for ex-ante prognoses, the timeseries resolution (here 15 minutes) is included in the horizon, because the horizon is relative to the end of the timeseries.

.. _resolutions:

Resolutions
^^^^^^^^^^^

Specifying a "resolution" is redundant for POST requests that contain both "values" and a "duration".
For GET requests such as *getMeterData* a "resolution" may be specified explicitly to obtain e.g. hourly or daily
values. If omitted, the web service will infer a resolution from the available data.
Valid resolutions for timeseries data in version 1 of the API are "PT15M" only.

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
