
.. _dev_why:

Why FlexMeasures adds value for software developers
----------------------------------------------------

FlexMeasures is designed to help with three basic needs of developers in the energy flexibility domain:


I need help with integrating real-time data and continuously computing new data
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

FlexMeasures is designed to make decisions based on data in an automated way. Data pipelining and dedicated machine learning tooling is crucial.

- API/CLI functionality to read in time series data
- Extensions for integrating 3rd party data, e.g. from `ENTSO-E <https://github.com/SeitaBV/flexmeasures-entsoe>`_ or `OpenWeatherMap <https://github.com/SeitaBV/flexmeasures-openweathermap>`_
- Forecasting for the upcoming hours
- Schedule optimization for flexible assets
- Reporters to combine time series data and create KPIs 


It's hard to correctly model data with different sources, resolutions, horizons and even uncertainties
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Much developer time is spent correcting data and treating it correctly, so that you know you are computing on the right knowledge.

FlexMeasures is built on the `timely-beliefs framework <https://github.com/SeitaBV/timely-beliefs>`_, so we model this real-world aspect accurately:

- Expected data properties are explicit (e.g. unit, time resolution)
- Incoming data is converted to fitting unit and time resolution automatically
- FlexMeasures also stores who thought that something happened (or that it will happen), and when they thought so
- Uncertainty can be modelled (useful for forecasting)


I want to build new features quickly, not spend days solving basic problems
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Building customer-facing apps & services is where developers make impact. We make their work easy.

- FlexMeasures has well-documented API endpoints and CLI commands to interact with its model and data
- You can extend it easily with your own logic by writing plugins
- A backend UI shows you your assets in maps and your data in plots. There is also support for plots to be available per API, for integration in your own frontend
- Multi-tenancy ― model multiple accounts on one server. Data is only seen/editable by authorized users in the right account


For more on FlexMeasures, head right over to :ref:`getting_started`.

