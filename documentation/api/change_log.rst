.. _api_change_log:

API change log
===============

.. note:: The FlexMeasures API follows its own versioning scheme. This is also reflected in the URL (e.g. `/api/v3_0`), allowing developers to upgrade at their own pace.

v3.0-20 | 2024-09-18
""""""""""""""""""""

-  Introduce (optional) pagination to the endpoint `/assets` (GET), also adding the `all_accessible` option to allow querying all accessible accounts in one go.


v3.0-19 | 2024-08-13
""""""""""""""""""""

- Allow passing a fixed price in the ``flex-context`` using the new fields ``consumption-price`` and ``production-price``, which are meant to replace the ``consumption-price-sensor`` and ``production-price-sensor`` fields, respectively.
- Allow posting a single instantaneous belief as a list of one element to `/sensors/data` (POST).
- Allow setting a SoC unit directly in some fields (formerly ``Float`` fields, and now ``Quantity`` fields), while still falling back on the contents of the ``soc-unit`` field, for backwards compatibility:

  - ``soc-at-start``
  - ``soc-min``
  - ``soc-max``

- Allow setting a unit directly in fields that already supported passing a time series:

  - ``soc-maxima``
  - ``soc-minima``
  - ``soc-targets``

- Allow passing a time series in fields that formerly only accepted passing a fixed quantity or a sensor reference:

  - ``power-capacity``
  - ``consumption-capacity``
  - ``production-capacity``
  - ``charging-efficiency``
  - ``discharging-efficiency``
  - ``storage-efficiency``
  - ``soc-gain``
  - ``soc-usage``

- Added API notation section on variable quantities.
- Updated section on scheduling; specifically, most flex-context and flex-model fields are now variable quantity fields, so a footnote now explains the few fields that aren't (yet) a variable quantity field.
- Removed section on singular vs plural keys, which is no longer valid for crucial endpoints.

v3.0-19 | 2024-08-09
""""""""""""""""""""

- Allow setting a SoC unit directly in some fields (formerly ``Float`` fields, and now ``Quantity`` fields), while still falling back on the contents of the ``soc-unit`` field, for backwards compatibility:

  - ``soc-at-start``
  - ``soc-min``
  - ``soc-max``

- Allow setting a unit directly in fields that already supported passing a time series:

  - ``soc-maxima``
  - ``soc-minima``
  - ``soc-targets``

- Allow passing a time series in fields that formerly only accepted passing a fixed quantity or a sensor reference:

  - ``power-capacity``
  - ``consumption-capacity``
  - ``production-capacity``
  - ``charging-efficiency``
  - ``discharging-efficiency``
  - ``storage-efficiency``
  - ``soc-gain``
  - ``soc-usage``


v3.0-18 | 2024-03-07
""""""""""""""""""""

- Add support for providing a sensor definition to the ``soc-minima``, ``soc-maxima`` and ``soc-targets`` flex-model fields for `/sensors/<id>/schedules/trigger` (POST).

v3.0-17 | 2024-02-26
""""""""""""""""""""

- Add support for providing a sensor definition to the ``site-power-capacity``, ``site-consumption-capacity`` and ``site-production-capacity`` flex-context fields for `/sensors/<id>/schedules/trigger` (POST).

v3.0-16 | 2024-02-26
""""""""""""""""""""

- Fix support for providing a sensor definition to the ``power-capacity`` flex-model field for `/sensors/<id>/schedules/trigger` (POST).

v3.0-15 | 2024-01-11
""""""""""""""""""""

- Support setting SoC constraints in the flex model for a given time period rather than a single datetime, using the new ``start``, ``end`` and/or ``duration`` fields of ``soc-maxima``, ``soc-minima`` and ``soc-targets``.

v3.0-14 | 2023-12-07
""""""""""""""""""""

- Fix API version listing (GET /api/v3_0) for hosts running on Python 3.8.

v3.0-13 | 2023-10-31
""""""""""""""""""""

- Read access to accounts, assets and sensors is given to external consultants (users with the *consultant* role who belong to a different organisation account) in case a consultancy relationship has been set up.
- The `/accounts/<id>` (GET) endpoint includes the account ID of its consultancy.
- Introduced the ``site-consumption-capacity`` and ``site-production-capacity`` to the ``flex-context`` field for `/sensors/<id>/schedules/trigger` (POST).

v3.0-12 | 2023-09-20
""""""""""""""""""""

- Introduced the ``power-capacity`` field under ``flex-model``, and the ``site-power-capacity`` field under ``flex-context``, for `/sensors/<id>/schedules/trigger` (POST).

v3.0-11 | 2023-08-02
""""""""""""""""""""

- Added REST endpoint for fetching one sensor: `/sensors/<id>` (GET)
- Added REST endpoint for adding a sensor: `/sensors` (POST)
- Added REST endpoint for patching a sensor: `/sensors/<id>` (PATCH)
- Added REST endpoint for deleting a sensor: `/sensors/<id>` (DELETE)

v3.0-10 | 2023-06-12
""""""""""""""""""""

- Introduced new ``flex-model`` fields for `/sensors/<id>/schedules/trigger` (POST):

  - ``storage-efficiency``
  - ``soc-minima``
  - ``soc-maxima``

- Introduced the ``database_redis`` optional field to the response of the endpoint `/health/ready` (GET).

v3.0-9 | 2023-04-26
"""""""""""""""""""

- Added missing documentation for the public endpoints for authentication and listing active API versions.
- Added REST endpoint for listing available services for a specific API version: `/api/v3_0` (GET). This functionality is similar to the *getService* endpoint for older API versions, but now also returns the full URL for each available service.

v3.0-8 | 2023-03-23
"""""""""""""""""""

- Added REST endpoint for listing accounts and their account roles: `/accounts` (GET)
- Added REST endpoint for showing an account and its account roles: `/accounts/<id>` (GET)

v3.0-7 | 2023-02-28
"""""""""""""""""""

- Fix premature deserialization of ``flex-context`` field for `/sensors/<id>/schedules/trigger` (POST).

v3.0-6 | 2023-02-01
"""""""""""""""""""

- Sunset all fields that were moved to ``flex-model`` and ``flex-context`` fields to `/sensors/<id>/schedules/trigger` (POST). See v3.0-5.

v3.0-5 | 2023-01-04
"""""""""""""""""""

- Introduced ``flex-model`` and ``flex-context`` fields to `/sensors/<id>/schedules/trigger` (POST). They are dictionaries and group pre-existing fields:

    - ``soc-at-start`` -> send in ``flex-model`` instead
    - ``soc-min`` -> send in ``flex-model`` instead
    - ``soc-max`` -> send in ``flex-model`` instead
    - ``soc-targets`` -> send in ``flex-model`` instead
    - ``soc-unit`` -> send in ``flex-model`` instead
    - ``roundtrip-efficiency`` -> send in ``flex-model`` instead
    - ``prefer-charging-sooner`` -> send in ``flex-model`` instead
    - ``consumption-price-sensor`` -> send in ``flex-context`` instead
    - ``production-price-sensor`` -> send in ``flex-context`` instead
    - ``inflexible-device-sensors`` -> send in ``flex-context`` instead

- Introduced the ``duration`` field to `/sensors/<id>/schedules/trigger` (POST) for setting a planning horizon explicitly.
- Allow posting ``soc-targets`` to `/sensors/<id>/schedules/trigger` (POST) that exceed the default planning horizon, and ignore posted targets that exceed the max planning horizon.
- Added a subsection on deprecating and sunsetting to the Introduction section.
- Added a subsection on describing flexibility to the Notation section.

v3.0-4 | 2022-12-08
"""""""""""""""""""

- Allow posting ``null`` values to `/sensors/data` (POST) to correctly space time series that include missing values (the missing values are not stored).
- Introduced the ``source`` field to `/sensors/data` (GET) to obtain data for a given source (ID).
- Fixed the JSON wrapping of the return message for `/sensors/data` (GET).
- Changed the Notation section:

    - Rewrote the section on filtering by source (ID) with a deprecation notice on filtering by account role and user ID.

v3.0-3 | 2022-08-28
"""""""""""""""""""

- Introduced ``consumption_price_sensor``, ``production_price_sensor`` and ``inflexible_device_sensors`` fields to `/sensors/<id>/schedules/trigger` (POST).

v3.0-2 | 2022-07-08
"""""""""""""""""""

- Introduced the "resolution" field to `/sensors/data` (GET) to obtain data in a given resolution.

v3.0-1 | 2022-05-08
"""""""""""""""""""

- Added REST endpoint for checking application health (readiness to accept requests): `/health/ready` (GET).

v3.0-0 | 2022-03-25
"""""""""""""""""""

- Added REST endpoint for listing sensors: `/sensors` (GET).
- Added REST endpoints for managing sensor data: `/sensors/data` (GET, POST).
- Added REST endpoints for managing assets: `/assets` (GET, POST) and `/assets/<id>` (GET, PATCH, DELETE).
- Added REST endpoints for triggering and getting schedules: `/sensors/<id>/schedules/<uuid>` (GET) and `/sensors/<id>/schedules/trigger` (POST).
- [**Breaking change**] Switched to plural resource names for REST endpoints:  `/users/<id>` (GET, PATCH) and `/users/<id>/password-reset` (PATCH).
- [**Breaking change**] Deprecated the following endpoints (NB replacement endpoints mentioned below no longer require the message "type" field):

    - *getConnection* -> use `/sensors` (GET) instead
    - *getDeviceMessage* -> use `/sensors/<id>/schedules/<uuid>` (GET) instead, where <id> is the sensor id from the "event" field and <uuid> is the value of the "schedule" field returned by `/sensors/<id>/schedules/trigger` (POST)
    - *getMeterData* -> use `/sensors/data` (GET) instead, replacing the "connection" field with "sensor"
    - *getPrognosis* -> use `/sensors/data` (GET) instead, replacing the "connection" field with "sensor"
    - *getService* -> use `/api/v3_0` (GET) instead (since v3.0-9), or consult the public API documentation instead, at https://flexmeasures.readthedocs.io
    - *postMeterData* -> use `/sensors/data` (POST) instead, replacing the "connection" field with "sensor"
    - *postPriceData* -> use `/sensors/data` (POST) instead, replacing the "market" field with "sensor"
    - *postPrognosis* -> use `/sensors/data` (POST) instead, replacing the "connection" field with "sensor"
    - *postUdiEvent* -> use `/sensors/<id>/schedules/trigger` (POST) instead, where <id> is the sensor id from the "event" field, and rename the following fields:

        - "datetime" -> "start"
        - "value -> "soc-at-start"
        - "unit" -> "soc-unit"
        - "targets" -> "soc-targets"
        - "soc_min" -> soc-min"
        - "soc_max" -> soc-max"
        - "roundtrip_efficiency" -> "roundtrip-efficiency"

    - *postWeatherData* -> use `/sensors/data` (POST) instead
    - *restoreData*

- Changed the Introduction section:

    - Rewrote the section on service listing for API versions to refer to the public documentation.
    - Rewrote the section on entity addresses to refer to *sensors* instead of *connections*.
    - Rewrote the sections on roles and sources into a combined section that refers to account roles rather than USEF roles.
    - Deprecated the section on group notation.

v2.0-7 | 2022-05-05
"""""""""""""""""""

*API v2.0 is removed.*

v2.0-6 | 2022-04-26
"""""""""""""""""""

*API v2.0 is sunset.*

v2.0-5 | 2022-02-13
"""""""""""""""""""

*API v2.0 is deprecated.*

v2.0-4 | 2022-01-04
"""""""""""""""""""

- Updated entity addresses in documentation, according to the fm1 scheme.
- Changed the Introduction section:

    - Rewrote the subsection on entity addresses to refer users to where they can find the entity addresses of their sensors.
    - Rewrote the subsection on sensor identification (formerly known as asset identification) to place the fm1 scheme front and center.

- Fixed the categorisation of the *postMeterData*, *postPrognosis*, *postPriceData* and *postWeatherData* endpoints from the User category to the Data category.

v2.0-3 | 2021-06-07
"""""""""""""""""""

- Updated all entity addresses in documentation according to the fm0 scheme, preserving backwards compatibility.
- Introduced the fm1 scheme for entity addresses for connections, markets, weather sensors and sensors.

v2.0-2 | 2021-04-02
"""""""""""""""""""

- [**Breaking change**] Switched the interpretation of horizons to rolling horizons.
- [**Breaking change**] Deprecated the use of ISO 8601 repeating time intervals to denote rolling horizons.
- Introduced the "prior" field for *postMeterData*, *postPrognosis*, *postPriceData* and *postWeatherData* endpoints.
- Changed the Introduction section:

    - Rewrote the subsection on prognoses to explain the horizon and prior fields.

- Changed the Simulation section:

    - Rewrote relevant examples using horizon and prior fields.

v2.0-1 | 2021-02-19
"""""""""""""""""""

- Added REST endpoints for managing users: `/users/` (GET), `/user/<id>` (GET, PATCH) and `/user/<id>/password-reset` (PATCH).

v2.0-0 | 2020-11-14
"""""""""""""""""""

- Added REST endpoints for managing assets: `/assets/` (GET, POST) and `/asset/<id>` (GET, PATCH, DELETE).


v1.3-14 | 2022-05-05
""""""""""""""""""""

*API v1.3 is removed.*

v1.3-13 | 2022-04-26
""""""""""""""""""""

*API v1.3 is sunset.*

v1.3-12 | 2022-02-13
""""""""""""""""""""

*API v1.3 is deprecated.*

v1.3-11 | 2022-01-05
""""""""""""""""""""

*Affects all versions since v1.3*.

- Changed and extended the *postUdiEvent* endpoint:

    - The recording time of new schedules triggered by calling the endpoint is now the time at which the endpoint was called, rather than the datetime of the sent state of charge (SOC).
    - Introduced the "prior" field for the purpose of communicating an alternative recording time, thereby keeping support for simulations.
    - Introduced an optional "roundtrip_efficiency" field, for use in scheduling.

v1.3-10 | 2021-11-08
""""""""""""""""""""

*Affects all versions since v1.3*.

- Fixed the *getDeviceMessage* endpoint for cases in which there are multiple schedules available, by returning only the most recent one.

v1.3-9 | 2021-04-21
"""""""""""""""""""

*Affects all versions since v1.0*.

- Fixed regression by partially reverting the breaking change of v1.3-8: Re-instantiated automatic inference of horizons for Post requests for API versions below v2.0, but changed to inference policy: now inferring the data was recorded **right after each event** took place (leading to a zero horizon for each data point) rather than **after the last event** took place (which led to a different horizon for each data point); the latter had been the inference policy before v1.3-8.

v1.3-8 | 2020-04-02
"""""""""""""""""""

*Affects all versions since v1.0*.

- [**Breaking change**, partially reverted in v1.3-9] Deprecated the automatic inference of horizons for *postMeterData*, *postPrognosis*, *postPriceData* and *postWeatherData* endpoints for API versions below v2.0.

v1.3-7 | 2020-12-16
"""""""""""""""""""

*Affects all versions since v1.0*.

- Separated the dual purpose of the "horizon" field in the *getMeterData* and *getPrognosis* endpoints by introducing the "prior" field:

    - The "horizon" field in GET endpoints is now always interpreted as a rolling horizon, regardless of whether it is stated as an ISO 8601 repeating time interval.
    - The *getMeterData* and *getPrognosis* endpoints now accept an optional "prior" field to select only data recorded before a certain ISO 8601 timestamp (replacing the unintuitive usage of the horizon field for specifying a latest time of belief).

v1.3-6 | 2020-12-11
"""""""""""""""""""

*Affects all versions since v1.0*.

- The *getMeterData* and *getPrognosis* endpoints now return the INVALID_SOURCE status 400 response in case the optional "source" field is used and no relevant sources can be found.

v1.3-5 | 2020-10-29
"""""""""""""""""""

*Affects all versions since v1.0*.

- Endpoints to POST meter data will now check incoming data to see if the required asset's resolution is being used ― upsampling is done if possible.
  These endpoints can now return the REQUIRED_INFO_MISSING status 400 response.
- Endpoints to GET meter data will return data in the asset's resolution ― downsampling to the "resolution" field is done if possible.
- As they need to determine the asset, all of the mentioned POST and GET endpoints can now return the UNRECOGNIZED_ASSET status 400 response.

v1.3-4 | 2020-06-18
"""""""""""""""""""

- Improved support for use cases of the *getDeviceMessage* endpoint in which a longer duration, between posting UDI events and retrieving device messages based on those UDI events, is required; the default *time to live* of UDI event identifiers is prolonged from 500 seconds to 7 days, and can be set as a config variable (`FLEXMEASURES_PLANNING_TTL`)

v1.3-3 | 2020-06-07
"""""""""""""""""""

- Changed backend support (API specifications unaffected) for scheduling charging stations to scheduling Electric Vehicle Supply Equipment (EVSE), in accordance with the Open Charge Point Interface (OCPI).

v1.3-2 | 2020-03-11
"""""""""""""""""""

- Fixed example entity addresses in simulation section

v1.3-1 | 2020-02-08
"""""""""""""""""""

- Backend change: the default planning horizon can now be set in FlexMeasures's configuration (`FLEXMEASURES_PLANNING_HORIZON`)

v1.3-0 | 2020-01-28
"""""""""""""""""""

- Introduced new event type "soc-with-targets" to support scheduling charging stations (see extra example for the *postUdiEvent* endpoint)
- The *postUdiEvent* endpoint now triggers scheduling jobs to be set up (rather than scheduling directly triggered by the *getDeviceMessage* endpoint)
- The *getDeviceMessage* now queries the job queue and database for an available schedule

v1.2-6 | 2022-05-05
"""""""""""""""""""

*API v1.2 is removed.*

v1.2-5 | 2022-04-26
"""""""""""""""""""

*API v1.2 is sunset.*

v1.2-4 | 2022-02-13
"""""""""""""""""""

*API v1.2 is deprecated.*

v1.2-3 | 2020-01-28
"""""""""""""""""""

- Updated endpoint descriptions with additional possible status 400 responses:

    - INVALID_DOMAIN for invalid entity addresses
    - UNKNOWN_PRICES for infeasible schedules due to missing prices

v1.2-2 | 2018-10-08
"""""""""""""""""""

- Added a list of registered types of weather sensors to the Simulation section and *postWeatherData* endpoint
- Changed example for the *postPriceData* endpoint to reflect Korean situation

v1.2-1 | 2018-09-24
"""""""""""""""""""

- Added a local table of contents to the Simulation section
- Added a description of the *postPriceData* endpoint in the Simulation section
- Added a description of the *postWeatherData* endpoint in the Simulation section
- Revised the subsection about posting power data in the Simulation section
- Revised the entity address for UDI events to include the type of the event

.. code-block:: json

    i.e.

    {
        "type": "PostUdiEventRequest",
        "event": "ea1.2021-01.io.flexmeasures.company:7:10:203:soc",
    }

    rather than the erroneously double-keyed:

    {
        "type": "PostUdiEventRequest",
        "event": "ea1.2021-01.io.flexmeasures.company:7:10:203",
        "type": "soc"
    }

v1.2-0 | 2018-09-08
"""""""""""""""""""

- Added a description of the *postUdiEvent* endpoint in the Prosumer and Simulation sections
- Added a description of the *getDeviceMessage* endpoint in the Prosumer and Simulation sections

v1.1-8 | 2022-05-05
"""""""""""""""""""

*API v1.1 is removed.*

v1.1-7 | 2022-04-26
"""""""""""""""""""

*API v1.1 is sunset.*

v1.1-6 | 2022-02-13
"""""""""""""""""""

*API v1.1 is deprecated.*

v1.1-5 | 2020-06-18
"""""""""""""""""""

- Fixed the *getConnection* endpoint where the returned list of connection names had been unnecessarily nested

v1.1-4 | 2020-03-11
"""""""""""""""""""

- Added support for posting daily and weekly prices for the *postPriceData* endpoint

v1.1-3 | 2018-09-08
"""""""""""""""""""

- Added the Simulation section:

    - Added information about setting up a new simulation
    - Added examples for calling the *postMeterData* endpoint
    - Added example for calling the *getPrognosis* endpoint

v1.1-2 | 2018-08-15
"""""""""""""""""""

- Added the *postPrognosis* endpoint
- Added the *postPriceData* endpoint
- Added a description of the *postPrognosis* endpoint in the Aggregator section
- Added a description of the *postPriceData* endpoint in the Aggregator and Supplier sections
- Added the *restoreData* endpoint for servers in play mode

v1.1-1 | 2018-08-06
"""""""""""""""""""

- Added the *getConnection* endpoint
- Added the *postWeatherData* endpoint
- Changed the Introduction section:

    - Added information about the sign of power values (production is negative)
    - Updated information about horizons (now anchored to the end of each time interval rather than to the start)
 
- Added an optional horizon to the *postMeterData* endpoint

v1.1-0 | 2018-07-15
"""""""""""""""""""

- Added the *getPrognosis* endpoint
- Changed the *getMeterData* endpoint to accept an optional resolution, source, and horizon
- Changed the Introduction section:

    - Added information about timeseries resolutions
    - Added information about sources
    - Updated information about horizons

- Added a description of the *getPrognosis* endpoint in the Supplier section

v1.0-4 | 2022-05-05
"""""""""""""""""""

*API v1.0 is removed.*

v1.0-3 | 2022-04-26
"""""""""""""""""""

*API v1.0 is sunset.*

v1.0-2 | 2022-02-13
"""""""""""""""""""

*API v1.0 is deprecated.*

v1.0-1 | 2018-07-10
"""""""""""""""""""

- Moved specifications to be part of the platform's Sphinx documentation:

    - Each API service is now documented in the docstring of its respective endpoint
    - Added sections listing all endpoints per version
    - Documentation includes specifications of **all** supported API versions (supported versions have a registered Flask blueprint)

v1.0-0 | 2018-07-10
"""""""""""""""""""

- Started change log
- Added Introduction section with notes regarding:

    - Authentication
    - Relevant roles for the API
    - Key notation
    - The addressing scheme for assets
    - Connection group notation
    - Timeseries notation
    - Prognosis notation
    - Units of timeseries data

- Added a description of the *getService* endpoint in the Introduction section
- Added a description of the *postMeterData* endpoint in the MDC section
- Added a description of the *getMeterData* endpoint in the Prosumer section
