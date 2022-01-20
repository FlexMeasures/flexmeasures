.. _modes-dev:

Modes
============

FlexMeasures can be run in specific modes (see the :ref:`modes-config` config setting).
This is useful for certain special situations. Two are supported out of the box and we document here 
how FlexMeasures behaves differently in these modes.

Demo
-------

In this mode, the server is assumed to be used as a demonstration tool. Most of the following adaptations therefore happen in the UI. 

- [Data] Demo data is often from an older source, and it's a hassle to change the year to the current year. FlexMeasures allows to set :ref:`demo-year-config` and when in ``demo`` mode, the current year will be translated to that year in the background.   
- [UI] Logged-in users can view queues on the demo server (usually only admins can do that)
- [UI] Demo servers often display login credentials, so visitors can try out functionality. Use the :ref:`demo-credentials-config` config setting to do this.
- [UI] The dashboard shows all non-empty asset groups, instead of only the ones for the current user.
- [UI] The analytics page mocks confidence intervals around power, price and weather data, so that the demo data doesn't need to have them. 
- [UI] The portfolio page mocks flexibility numbers and a mocked control action.

Play
------

In this mode, the server is assumed to be used to run simulations.

Big features
^^^^^^^^^^^^^

- [API] The inferred recording time of incoming data is immediately after the event took place, rather than the actual time at which the server received the data.
- [API] Posting price or weather data does not trigger forecasting jobs.
- [API] The ``restoreData`` endpoint is registered, enabling database resets through the API.
- [API] When posting weather data for a new location, a new weather sensor is automatically created, instead of returning the nearest available weather sensor to post data to.

.. note:: A former feature of play mode is now a separate config setting. To allow overwriting existing data when saving data to the database, use :ref:`overwrite-config`.

Small features
^^^^^^^^^^^^^^^

- [API] Posted UDI events are not enforced to be consecutive.
- [API] Names in ``GetConnectionResponse`` are the connections' unique database names rather than their display names (this feature is planned to be deprecated).
- [UI] The dashboard plot showing the latest power value is not enforced to lie in the past (in case of simulating future values).
