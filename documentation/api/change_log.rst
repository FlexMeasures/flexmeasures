.. _api_change_log:

API change log
===============

.. note:: The FlexMeasures API follows its own versioning scheme. This is also reflected in the URL, allowing developers to upgrade at their own pace.


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

- REST endpoints for managing users: `/users/` (GET), `/user/<id>` (GET, PATCH) and `/user/<id>/password-reset` (PATCH).

v2.0-0 | 2020-11-14
"""""""""""""""""""

- REST endpoints for managing assets: `/assets/` (GET, POST) and `/asset/<id>` (GET, PATCH, DELETE).


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

- [**Breaking change**, partially reverted in v1.3-9] Deprecated the automatic inference of horizons for *postMeterData*, *postPrognosis*, *postPriceData* and *postWeatherData* endpoints for API version below v2.0.

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
- As they need to determine the asset, all of the mentioned POST and GET endpoints can now return the UNRECOGNIZED_ASSET status 4000 response.

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
