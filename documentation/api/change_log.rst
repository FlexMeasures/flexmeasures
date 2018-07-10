.. _change_log:

Change log
==========

v1.1-0
""""""

- Added the *getPrognosis* endpoint
- Added the *postPrognosis* endpoint
- Added information about timeseries resolution in the Introduction section
- Added a description of the *getPrognosis* endpoint in the Supplier section
- Added a description of the *postPrognosis* endpoint in the Aggregator section

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
