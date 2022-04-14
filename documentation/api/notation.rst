.. _api_notation:

Notation
--------

This page helps you to construct messages to the FlexMeasures API. Please consult the endpoint documentation first. Here we dive into topics useful across endpoints.


Singular vs plural keys
^^^^^^^^^^^^^^^^^^^^^^^

Throughout this document, keys are written in singular if a single value is listed, and written in plural if multiple values are listed, for example:

.. code-block:: json

    {
        "keyToValue": "this is a single value",
        "keyToValues": ["this is a value", "and this is a second value"]
    }

The API, however, does not distinguish between singular and plural key notation.


Sensors and entity addresses
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In many API endpoints, sensors are identified by their ID, e.g. ``/sensors/45``. However, all sensors can also be identified with an entity address following the EA1 addressing scheme prescribed by USEF[1],
which is mostly taken from IETF RFC 3720 [2].

This is the complete structure of an EA1 address:

.. code-block:: json

    {
        "sensor": "ea1.{date code}.{reversed domain name}:{locally unique string}"
    }

Here is a full example for an entity address of a sensor in FlexMeasures:

.. code-block:: json

    {
        "sensor": "ea1.2021-02.io.flexmeasures.company:fm1.73"
    }

where FlexMeasures runs at `company.flexmeasures.io` (which the current domain owner started using in February 2021), and the locally unique string uses the `fm1` scheme (see below) to identify sensor ID 73.

Assets are listed at:

.. code-block:: html

    https://company.flexmeasures.io/assets

The full entity addresses of all of the asset's sensors can be obtained on the asset's page, e.g. for asset 81:

.. code-block:: html

    https://company.flexmeasures.io/assets/81


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


Types of sensor identification used in FlexMeasures
""""""""""""""""""""""""""""""""""""""""""""""""""""

FlexMeasures expects the locally unique string string to contain information in a certain structure.
We distinguish type ``fm0`` and type ``fm1`` FlexMeasures entity addresses.

The ``fm1`` scheme is the latest version.
It uses the fact that all FlexMeasures sensors have unique IDs.

.. code-block::

    ea1.2021-01.io.flexmeasures:fm1.42
    ea1.2021-01.io.flexmeasures:fm1.<sensor_id>

.. todo:: UDI events are not yet modelled in the fm1 scheme

The ``fm0`` scheme is the original scheme.
It identified different types of sensors (such as grid connections, weather sensors and markets) in different ways.
The ``fm0`` scheme has been deprecated for the most part and is no longer supported officially.
Only UDI events still need to be sent using the fm0 scheme.

.. code-block::

    ea1.2021-01.io.flexmeasures:fm0.40:30:302:soc
    ea1.2021-01.io.flexmeasures:fm0.<owner_id>:<sensor_id>:<event_id>:<event_type>


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

Notation for v1, v2 and v3
""""""""""""""""""""""""""

For version 1, 2 and 3 of the API, only equidistant timeseries data is expected to be communicated. Therefore:

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

When POSTing data, FlexMeasures checks this computed resolution against the required resolution of the sensors which are posted to. If these can't be matched (through upsampling), an error will occur.

GET requests (such as *getMeterData*) return data in the resolution which the sensor is configured for.
A "resolution" may be specified explicitly to obtain the data in downsampled form, 
which can be very beneficial for download speed. The specified resolution needs to be a multiple
of the sensor's resolution, e.g. hourly or daily values if the sensor's resolution is 15 minutes.


.. _sources:

Sources
-------

Requests for data may limit the data selection by specifying a source, for example, a specific user.
Account roles are also valid source selectors.
For example, to obtain data originating from either a meter data company or user 42, include the following:

.. code-block:: json

    {
        "sources": ["MDC", "42"],
    }

Here, "MDC" is the name of the account role for meter data companies.


.. _units:

Units
^^^^^

From API version 3 onwards, we are much more flexible with sent units.
A valid unit for timeseries data is any unit that is convertible to the configured sensor unit registered in FlexMeasures.
So, for example, you can send timeseries data with "W" unit to a "kW" sensor.
And if you wish to do so, you can even send a timeseries with "kWh" unit to a "kW" sensor.
In this case, FlexMeasures will convert the data using the resolution of the timeseries.

For API versions 1 and 2, the unit sent needs to be an exact match with the sensor unit, and only "MW" is allowed for power sensors.

.. _signs:

Signs of power values
^^^^^^^^^^^^^^^^^^^^^

USEF recommends to use positive power values to indicate consumption and negative values to indicate production, i.e.
to take the perspective of the Prosumer.
If an asset has been configured as a pure producer or pure consumer, the web service will help avoid mistakes by checking the sign of posted power values.
