.. _api_notation:

Notation
--------

This page helps you to construct messages to the FlexMeasures API. Please consult the endpoint documentation first. Here we dive into topics useful across endpoints.


Flex-model and flex-context values
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The formats accepted by flex-model and flex-context fields are described under
:ref:`variable_quantities` in the :ref:`flexibility_configuration` concept.


Time series and beliefs
^^^^^^^^^^^^^^^^^^^^^^^

For the event, frequency, resolution, and belief-time notation shared across
FlexMeasures, see :ref:`time_series_and_beliefs`.


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

For the ``GET /api/v3_0/sensors/<id>/data`` endpoint specifically, source filtering supports:

- ``source``: filter by data source ID
- ``source-account``: filter by the account ID linked to data sources
- ``source-type``: filter by the type of data source (e.g. 'forecaster' or 'scheduler')

.. note::

   If schedules are recorded on the same sensor as measurements or forecasts, source filtering can be used to distinguish them.
   An alternative is to model schedules on dedicated sensors; see :ref:`one_or_multiple_sensors`.


.. _units:

Units
^^^^^

The FlexMeasures API is quite flexible with units.
Units are validated and converted using the `Pint <https://pint.readthedocs.io>`_ library.
A valid unit for timeseries data is any unit that is convertible to the unit configured on the target sensor in FlexMeasures.

The following categories of unit conversions are supported:

- **Different prefixes** — e.g. posting data in "W" to a "kW" sensor, or "MW" to a "W" sensor.
- **Equivalent units** — e.g. posting "J/s" to a "W" sensor (since 1 J/s = 1 W), or "m/s" to a "km/h" sensor.
- **Flow ↔ stock conversions** — e.g. posting "kWh" (energy) to a "kW" (power) sensor. FlexMeasures automatically divides by the event resolution to convert between units of stock and units of flow, and vice versa.
- **Currency codes** — three-letter ISO 4217 currency codes (e.g. "EUR", "KRW") are valid units. Note that converting between different currencies (e.g. "EUR" to "USD") requires a sensor that records conversion rates over time.
- **Percentages** — "%" can be posted to any unit if a capacity is known (e.g. a state-of-charge percentage to a "kWh" sensor).
- **Compound units** — units built from combinations are automatically simplified to the most compact form (e.g. "kW·EUR/MWh" is simplified to "EUR/h").

For example, the following ``unit`` values are all accepted when posting data to a "kW" sensor:

+------------+---------------------------------+
| Unit       | Accepted because                |
+============+=================================+
| ``"kW"``   | exact match                     |
+------------+---------------------------------+
| ``"W"``    | different SI prefix             |
+------------+---------------------------------+
| ``"MW"``   | different SI prefix             |
+------------+---------------------------------+
| ``"J/s"``  | equivalent unit (1 J/s = 1 W)   |
+------------+---------------------------------+
| ``"kWh"``  | flow-to-stock (uses resolution) |
+------------+---------------------------------+

.. seealso::

   For the full list of supported conversions and the underlying implementation details, see the :mod:`flexmeasures.utils.unit_utils` module documentation.

.. _signs:

Signs of power values
^^^^^^^^^^^^^^^^^^^^^
In general, FlexMeasures lets you store data as you want. Negative power values to indicate production, positive consumption - or the other way around.

We'd recommend to use positive power values to indicate consumption and negative values to indicate production, i.e.
-to take the perspective of the Prosumer.

Read more at :ref:`signs_of_power_beliefs` about our treatment of data, which includes data you send in, or you get from forecasts and schedules
(hint: you are free to define the sign for your data, but it might affect how you receive your schedules).

The ``GET /api/v3_0/sensors/<id>/schedules/<uuid>`` endpoint supports three sign conventions via the ``sign-convention`` query parameter:

- ``consumption-positive`` (**default**): schedules are returned with consumption as positive values and production as negative values, regardless of how they are stored in the database.
- ``production-positive``: schedules are returned with production as positive values and consumption as negative values.
- ``wysiwyg`` (*what-you-see-is-what-you-get*): schedules are returned with the same sign as database values and as seen in the UI charts.
  The values indicate exactly what was stored, which was itself governed by the sensor's ``consumption_is_positive`` attribute (if present) or the scheduler's default convention (which stored production as positive values in the database).
