.. _api_notation:

Notation
--------

This page helps you to construct messages to the FlexMeasures API. Please consult the endpoint documentation first. Here we dive into topics useful across endpoints.


.. _variable_quantities:

Variable quantities
^^^^^^^^^^^^^^^^^^^^^^^

Many API fields deal with variable quantities, for example, :ref:`flex-model <flex_models_and_schedulers>` and :ref:`flex-context <flex_context>` fields.
Unless stated otherwise, values of such fields can take one of the following forms:

- A fixed quantity, to describe steady constraints such as a physical power capacity.
  For example:

  .. code-block:: json

     {
         "power-capacity": "15 kW"
     }

- A variable quantity defined at specific moments in time, to describe dynamic constraints/preferences such as target states of charge.

  .. code-block:: json

     {
         "soc-targets": [
             {"datetime": "2024-02-05T08:00:00+01:00", "value": "8.2 kWh"},
             ...
             {"datetime": "2024-02-05T13:00:00+01:00", "value": "2.2 kWh"}
         ]
     }

- A variable quantity defined for specific time ranges, to describe dynamic constraints/preferences such as usage forecasts.

  .. code-block:: json

     {
         "soc-usage": [
             {"start": "2024-02-05T08:00:00+01:00", "duration": "PT2H", "value": "10.1 kW"},
             ...
             {"start": "2024-02-05T13:00:00+01:00", "end": "2024-02-05T13:15:00+01:00", "value": "10.3 kW"}
         ]
     }

  Note the two distinct ways of specifying a time period (``"end"`` in combination with ``"duration"`` also works).

  .. note:: In case a field defines partially overlapping time periods, FlexMeasures automatically resolves this.
            By default, time periods that are defined earlier in the list take precedence.
            Fields that deviate from this policy will note so explicitly.
            (For example, for fields dealing with capacities, the minimum is selected instead.)

- A reference to a sensor that records a variable quantity, which allows cross-referencing to dynamic contexts that are already recorded as sensor data in FlexMeasures. For instance, a site's contracted consumption capacity that changes over time.

  .. code-block:: json

     {
         "site-consumption-capacity": {"sensor": 55}
     }

  The unit of the data is specified on the sensor.


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


In all current versions of the FlexMeasures API, only equidistant timeseries data is expected to be communicated. Therefore:

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
^^^^^^^

Requests for data may filter by source. FlexMeasures keeps track of the data source (the data's author, for example, a user, forecaster or scheduler belonging to a given organisation) of time series data.
For example, to obtain data originating from data source 42, include the following:

.. code-block:: json

    {
        "source": 42,
    }

Data source IDs can be found by hovering over data in charts.

.. _units:

Units
^^^^^

The FlexMeasures API is quite flexible with sent units.
A valid unit for timeseries data is any unit that is convertible to the configured sensor unit registered in FlexMeasures.
So, for example, you can send timeseries data with "W" unit to a "kW" sensor.
And if you wish to do so, you can even send a timeseries with "kWh" unit to a "kW" sensor.
In this case, FlexMeasures will convert the data using the resolution of the timeseries.

.. _signs:

Signs of power values
^^^^^^^^^^^^^^^^^^^^^

USEF recommends to use positive power values to indicate consumption and negative values to indicate production, i.e.
to take the perspective of the Prosumer.
If an asset has been configured as a pure producer or pure consumer, the web service will help avoid mistakes by checking the sign of posted power values.
