.. _time_series_and_beliefs:

Time series, events and beliefs
===============================

Time-series data in FlexMeasures has two distinct timelines: when an event
happens, and when a value about that event is recorded. These concepts apply
across the API, scheduling configuration, forecasts, schedules, and
measurements.

.. contents::
   :local:
   :depth: 2


Time series and events
----------------------

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

This intuitive convention allows us to reduce communication by sending univariate time series as arrays.


In all current versions of the FlexMeasures API, only equidistant timeseries data is expected to be communicated. Therefore:

- only the array notation should be used (first notation from above),
- "start" should be a timestamp on the hour or a multiple of the sensor resolution thereafter (e.g. "16:10" works if the resolution is 5 minutes), and
- "duration" should also be a multiple of the sensor resolution.

For non-instantaneous sensors, FlexMeasures floors off-clock datetimes to the
sensor's resolution by default when ingesting sensor data. For example, data
posted with ``"start": "2026-05-12T08:29:58+02:00"`` to a 15-minute sensor is
saved from ``2026-05-12T08:15:00+02:00``. Set the sensor attribute
``"floor_datetimes_to_resolution": false`` to disable this behaviour.


.. _beliefs:

Beliefs and their recording time
--------------------------------

For every time-series value, FlexMeasures records both when the event happens
and when that value became known or was asserted. This lets you distinguish,
for example, a day-ahead forecast from a meter reading about the same physical
event, and reconstruct what was known at an earlier point in time.

FlexMeasures calls each such assertion a *belief*. Its recording time is the
``belief_time``. The ``belief_horizon`` expresses how far the belief time is
from when the event becomes knowable:

``belief_horizon = knowledge_time - belief_time``

For a physical event, the knowledge time is the event end. Consequently, a
positive horizon describes a belief made before the event was fully known,
while a negative horizon describes an *ex post* belief made after it. For an
economic event, the knowledge time can instead be a gate-closure time.

The following physical event starts at 13:00 and ends at 13:15. A belief
recorded at 07:15 therefore has a six-hour belief horizon:

.. mermaid::

   flowchart LR
       B["07:15<br/><b>belief_time</b>"]
       S["13:00<br/><b>event_start</b>"]
       E["13:15<br/><b>event_end</b><br/>knowledge time"]
       B -->|"5 h 45 min"| S
       S -->|"15 min"| E
       B -.->|"belief_horizon = PT6H"| E

Although ``event_start - belief_time`` is 5 hours and 45 minutes, the belief
horizon is six hours because this physical event becomes fully knowable only
at ``event_end``.

.. note::

   FlexMeasures uses the
   `timely-beliefs data model <https://github.com/SeitaBV/timely-beliefs/#the-data-model>`_
   for these concepts. Its more general ``knowledge_time`` also covers events
   whose natural knowledge time differs from ``event_end``.


Querying by belief time
^^^^^^^^^^^^^^^^^^^^^^^

Some GET endpoints accept two optional filters:

- ``prior`` selects beliefs recorded at or before an absolute timestamp.
- ``horizon`` selects beliefs whose horizon is at least the given duration.

When both are supplied, a belief must satisfy both conditions:

``belief_time <= prior AND belief_horizon >= horizon``

The next example queries with ``prior=10:00`` and ``horizon=PT2H``. The three
beliefs concern consecutive hourly events, and the timeline shows why only one
is selected:

.. mermaid::

   timeline
       title Query with prior = 10:00 and horizon = PT2H
       09:30 : EXCLUDED — 10 kWh event; horizon 1 h 30 min
             : SELECTED — 20 kWh event; horizon 2 h 30 min
       10:00 : prior cutoff
             : 10 kWh event starts
       10:30 : EXCLUDED — 30 kWh event; after prior
       11:00 : 10 kWh event ends
             : 20 kWh event starts
       12:00 : 20 kWh event ends
             : 30 kWh event starts
       13:00 : 30 kWh event ends

The 10 kWh belief was recorded before the prior cutoff, but its 1-hour-30-minute
horizon is too short. The 20 kWh belief passes both filters. The 30 kWh belief
has a sufficiently long horizon, but was recorded after the prior cutoff.

Positive horizons are useful for selecting forecasts made sufficiently far in
advance. Negative horizons can select meter readings received within an
allowed delay after the event.

.. note::

   Beliefs can also be filtered by their source; see :ref:`sources`.


.. _prognoses:

Setting the belief time
^^^^^^^^^^^^^^^^^^^^^^^

Some POST endpoints accept two optional timing fields to set when posted
beliefs were recorded. Use no more than one in a request:

- ``prior`` assigns the same absolute belief time to every value.
- ``horizon`` derives each belief time relative to the corresponding event's
  knowledge time.

If neither field is supplied, FlexMeasures uses the time at which the message
arrives. Consider two consecutive hourly energy events:

.. code-block:: json

   {
       "values": [10, 20],
       "start": "2016-05-01T13:00:00Z",
       "duration": "PT2H",
       "unit": "kWh"
   }

The timing field changes only the belief times; the events still start at 13:00
and 14:00.

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Timing field
     - 10 kWh at 13:00
     - 20 kWh at 14:00
   * - omitted
     - message arrival time
     - message arrival time
   * - ``"prior": "2016-05-01T11:00:00Z"``
     - belief time 11:00
     - belief time 11:00
   * - ``"horizon": "PT2H"``
     - belief time 12:00
     - belief time 13:00

With ``horizon=PT2H``, the first event's belief time is two hours before its
14:00 event end, and the second is two hours before its 15:00 event end.

Negative horizons are supported as an extension to ISO 8601 durations. For
example, ``"horizon": "-PT10M"`` records the two belief times as 14:10 and
15:10: ten minutes after the respective event ends.

Use either ``prior`` or ``horizon`` when posting data. If both are supplied,
``prior`` takes precedence and ``horizon`` is ignored.


.. _frequency_and_resolution:

Frequency and resolution
------------------------

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
If these can't be matched through upsampling or downsampling, an error will occur.
Off-clock event starts for non-instantaneous sensors are floored to the sensor's resolution by default.
The sensor attribute ``floor_datetimes_to_resolution`` can be set to ``false`` to keep incoming datetimes unchanged.
This flooring behaviour is distinct from the existing ``frequency`` sensor attribute, which rounds incoming instantaneous measurements to a configured Pandas frequency.

GET requests (such as */sensors/data*) return data with a frequency either equal to the resolution that the sensor is configured for (for non-instantaneous sensors), or a default frequency befitting (in our opinion) the requested time interval.
A "resolution" may be specified explicitly to obtain the data in downsampled form, which can be very beneficial for download speed.
For non-instantaneous sensors, the specified resolution needs to be a multiple of the sensor's resolution, e.g. hourly or daily values if the sensor's resolution is 15 minutes.
For instantaneous sensors, the specified resolution is interpreted as a request for data in a specific frequency.
The resolution of the underlying data will remain zero (and the returned message will say so).
