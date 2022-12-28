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

The ``fm0`` scheme is the original scheme.
It identified different types of sensors (such as grid connections, weather sensors and markets) in different ways.
The ``fm0`` scheme has been deprecated and is no longer supported officially.


Timeseries
^^^^^^^^^^

Timestamps and durations are consistent with the ISO 8601 standard.
The frequency of the data is implicit (from duration and number of values), while the resolution of the data is explicit, see :ref:`frequency_and_resolution`.

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


.. _describing_flexibility:

Describing flexibility
^^^^^^^^^^^^^^^^^^^^^^^

FlexMeasures computes schedules for energy systems that consist of multiple devices that consume and/or produce electricity.
We model a device as an asset with a power sensor, and compute schedules only for flexible devices, while taking into account inflexible devices.

To compute a schedule, FlexMeasures first needs to assess the flexibility state of the system.
This is described by the `flex model` (information about the state and possible actions of the flexible device) and the `flex-context`
(information about the system as a whole, in order to assess the value of activating flexibility).

This information goes beyond the usual time series recorded by an asset's sensors. It's being sent through the API when triggering schedule computation.
Some parts of it can be persisted on the asset & sensor model as attributes (that's design work in progress). 

We distinguish the information with two groups:

Flex model
""""""""""""

The flexibility model describes to the scheduler what the flexible asset's state is,
and what constraints or preferences should be taken into account.
Which type of flexibility model is relevant to a scheduler usually relates to the type of device.

Usually, not the whole flexibility model is needed.
FlexMeasures can infer missing values in the flex model, and even get them (as default) from the sensor's attributes.
This means that API and CLI users don't have to send the whole flex model every time.

Here are the three types of flexibility models you can expect to be built-in:

1) For storage devices (e.g. batteries, charge points, electric vehicle batteries connected to charge points), the schedule deals with the state of charge (SOC).
    
    The possible flexibility parameters are:

    - ``soc-at-start`` (defaults to 0)
    - ``soc-unit`` (kWh or MWh)
    - ``soc-min`` (defaults to 0)
    - ``soc-max`` (defaults to max soc target)
    - ``soc-targets`` (defaults to NaN values)
    - ``roundtrip-efficiency`` (defaults to 100%)
    - ``prefer-charging-sooner`` (defaults to True, also signals a preference to discharge later)

  For some examples, see the `[POST] /sensors/(id)/schedules/trigger <../api/v3_0.html#post--api-v3_0-sensors-(id)-schedules-trigger>`_ endpoint docs.

2) Shiftable process
   
   .. todo:: A simple algorithm exists, needs integration into FlexMeasures and asset type clarified.

3) Heat pumps
   
   .. todo:: Also work in progress, needs model for heat loss compensation.

In addition, folks who write their own custom scheduler (see :ref:`plugin_customization`) might also require their custom flexibility model.
That's no problem, FlexMeasures will let the scheduler decide which flexibility model is relevant and how it should be validated. 

.. note:: We also aim to model situations with more than one flexible asset, with different types of flexibility.
     This is ongoing architecture design work, and therefore happens in development settings, until we are happy 
     with the outcomes. Thoughts welcome :) 


Flex context
"""""""""""""

With the flexibility context, we aim to describe the system in which the flexible assets operates:

- ``inflexible-device-sensors`` ― power sensors that are relevant, but not flexible, such as a sensor recording rooftop solar power connected behind the main meter, whose production falls under the same contract as the flexible device(s) being scheduled
- ``consumption-price-sensor`` ― the sensor which defines costs/revenues of consuming energy
- ``production-price-sensor`` ― the sensor which defines cost/revenues of producing energy

These should be independent on the asset type and consequently also do not depend on which scheduling algorithm is being used.


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

.. _frequency_and_resolution:

Frequency and resolution
^^^^^^^^^^^^^^^^^^^^^^^^

FlexMeasures handles two types of time series, which can be distinguished by defining the following timing properties for events recorded by sensors:

- Frequency: how far apart events occur (a constant duration between event starts)
- Resolution: how long an event lasts (a constant duration between the start and end of an event)

.. note:: FlexMeasures runs on Pandas, and follows Pandas terminology accordingly.
          The term frequency as used by Pandas is the reciprocal of the `SI quantity for frequency <https://en.wikipedia.org/wiki/SI_derived_unit>`_.

1. The first type of time series describes non-instantaneous events such as average hourly wind speed.
   For this case, it is commonly assumed that ``frequency == resolution``.
   That is, events follow each other sequentially and without delay.

2. The second type of time series describes instantaneous events (zero resolution) such as temperature at a given time.
   For this case, we have ``frequency != resolution``.

Specifying a frequency and resolution is redundant for POST requests that contain both "values" and a "duration" ― FlexMeasures computes the frequency by dividing the duration by the number of values, and, for sensors that record non-instantaneous events, assumes the resolution of the data is equal to the frequency.

When POSTing data, FlexMeasures checks this inferred resolution against the required resolution of the sensors that are posted to.
If these can't be matched (through upsampling), an error will occur.

GET requests (such as */sensors/data*) return data with a frequency either equal to the resolution that the sensor is configured for (for non-instantaneous sensors), or a default frequency befitting (in our opinion) the requested time interval.
A "resolution" may be specified explicitly to obtain the data in downsampled form, which can be very beneficial for download speed.
For non-instantaneous sensors, the specified resolution needs to be a multiple of the sensor's resolution, e.g. hourly or daily values if the sensor's resolution is 15 minutes.
For instantaneous sensors, the specified resolution is interpreted as a request for data in a specific frequency.
The resolution of the underlying data will remain zero (and the returned message will say so).


.. _sources:

Sources
-------

Requests for data may filter by source. FlexMeasures keeps track of the data source (the data's author, for example, a user, forecaster or scheduler belonging to a given organisation) of time series data.
For example, to obtain data originating from data source 42, include the following:

.. code-block:: json

    {
        "source": 42,
    }

Data source IDs can be found by hovering over data in charts.

.. note:: Older API version (< 3) accepted user IDs (integers), account roles (strings) and lists thereof, instead of data source IDs (integers).


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
