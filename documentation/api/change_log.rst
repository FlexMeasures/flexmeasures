.. _change_log:

Change log
==========

v1.1-2
""""""

- Added the *postPrognosis* endpoint
- Added the *postPriceData* endpoint
- Added a description of the *postPrognosis* endpoint in the Aggregator section
- Added a description of the *postPriceData* endpoint in the Aggregator and Supplier sections

.. ifconfig:: BVP_MODE == "play"

    - Added the *restoreData* endpoint

v1.1-1
""""""

- Added the *getConnection* endpoint
- Added the *postWeatherData* endpoint
- Changed the Introduction section:

    - Added information about the sign of power values (production is negative)
    - Updated information about horizons (now anchored to the end of each time interval rather than to the start)
 
- Added an optional horizon to the *postMeterData* endpoint

v1.1-0
""""""

- Added the *getPrognosis* endpoint
- Changed the *getMeterData* endpoint to accept an optional resolution, source, and horizon
- Changed the Introduction section:

    - Added information about timeseries resolutions
    - Added information about sources
    - Updated information about horizons

- Added a description of the *getPrognosis* endpoint in the Supplier section

v1.0-1
""""""

- Moved specifications to be part of the platform's Sphinx documentation:

    - Each API service is now documented in the docstring of its respective endpoint
    - Added sections listing all endpoints per version
    - Documentation includes specifications of **all** supported API versions (supported versions have a registered Flask blueprint)


v1.0-0
""""""

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
