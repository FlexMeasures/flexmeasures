.. |check_| raw:: html

    <input checked=""  disabled="" type="checkbox">

.. |uncheck_| raw:: html

    <input disabled="" type="checkbox">

.. _note_on_datamodel_transition:

A note on the ongoing data model transition
============================================

FlexMeasures is already ~5 years in the making. It's a normal process for well-maintained software to update architectural principles during such a time.

We are finishing up a refactoring which affects the data model, and if you are using FlexMeasures on your own server, we want you to know the following:
    

We have your back
------------------

By upgrading FlexMeasures one minor version at a time, you get the most out of our transition tools, including database upgrades (moving data over from the old to the new model automatically), plugin compatibility warnings, deprecation warnings for upcoming sunsets, and blackout tests (:ref:`more info here<api_deprecation>`).
If you still work with the old model and are having trouble to transition data to the current model, let us know.


This transition is in your interest, as well
----------------------------------------------

We did this transition so we could make FlexMeasures even more useful. For instance: support for more kinds of assets (energy plus related sensors), and better support for forecasting, scheduling and reporting.


What are the big changes?
-----------------------------

There are two important transitions that happened in this transition:

1. First, we deprecated the specific data types ``Asset``, ``Market`` and ``WeatherSensor``. We learned that to manage energy flexibility, you need all sort of sensors, and thus a more generalisable data model. When we modelled assets and sensors, we were also better able to differentiate the business from the data world.
2. Second, we fully integrated the `timely-beliefs framework <https://github.com/SeitaBV/timely-beliefs>`_ as the model for our time series data, which brings some major benefits for programmers as it lets us handle uncertain, multi-source time series data in a special Pandas data frame.

For the curious, here are visualisations of where we were before and where we're going (click image for large versions).

The old model:

.. image:: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/FlexMeasures-CurrentDataModel.png
    :target: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/FlexMeasures-CurrentDataModel.png
    :align: center
..    :scale: 40%

The future model (work in progress):

.. image:: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/FlexMeasures-NewDataModel.png
    :target: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/FlexMeasures-NewDataModel.png
    :align: center
..    :scale: 40%


What is going on in detail?
------------------------------

We made `a technical roadmap on Github Projects <https://github.com/FlexMeasures/flexmeasures/projects>`_.

Here is a brief list:

- |check_| `Data model based on timely beliefs <https://github.com/FlexMeasures/flexmeasures/projects/3>`_: Our data model of beliefs about timed events, timely-beliefs, is being more tightly integrated into FlexMeasures. We do this so we can take advantage of timely-belief's capabilities more and increase the focus of FlexMeasures on features.
- |check_| `Support Sensor and Asset diversity <https://github.com/FlexMeasures/flexmeasures/projects/9>`_: We are generalizing our database structure for organising energy data, to support all sorts of sensors and assets, and are letting users move their data to the new database model. We do this so we can better support the diverse set of use cases for energy flexibility.
- |check_| `Update API endpoints for time series communication <https://github.com/FlexMeasures/flexmeasures/projects/13>`_: We are updating our API with new endpoints for communicating time series data, thereby consolidating a few older endpoints into a better standard. We do this so we can both simplify our API and documentation, and support a diversity of sensors.
- |check_| `Update CLI commands for setting up Sensors and Assets <https://github.com/FlexMeasures/flexmeasures/projects/14>`_: We are updating our CLI commands to reflect the new database structure. We do this to facilitate setting up structure for new users.
- |check_| `Update UI views for Sensors and Assets <https://github.com/FlexMeasures/flexmeasures/projects/10>`_: We are updating our UI views (dashboard maps and analytics charts) according to our new database structure for organising energy data. We do this so users can customize what they want to see.
- |check_| `Deprecate old database models <https://github.com/FlexMeasures/flexmeasures/projects/11>`_: We are deprecating the Power, Price and Weather tables in favour of the TimedBelief table, and deprecating the Asset, Market and WeatherSensor tables in favour of the Sensor and GenericAsset tables. We are doing this to clean up the code and database structure.
- |uncheck_| `Infrastructure for reporting on sensors <https://github.com/FlexMeasures/flexmeasures/projects/19>`_: We are working on a backend infrastructure for sensors that record reports based on other sensors, like daily costs and aggregate power flow.
- |uncheck_| `Scheduling of sensors <https://github.com/FlexMeasures/flexmeasures/projects/6>`_: We are extending our database structure for Sensors with actuator functionality, and are moving to a model store where scheduling models can be registered. We do this so we can provide better plugin support for scheduling a diverse set of devices.
- |uncheck_| `Forecasting of sensors <https://github.com/FlexMeasures/flexmeasures/projects/8>`_: We are revising our forecasting tooling to support fixed-viewpoint forecasts. We do this so we can better support decision moments with the most recent expectations about relevant sensors.


The state of the transition (July 2023, v0.15.0)
---------------------------------------------------

Project 9 was implemented with the release of v0.8.0. This work moved a lot of structure over, as well as actual data and some UI (dashboard, assets). We believe that was the hardest part.

In project 13, we began work on a new API version (v3) that supports only the new data model (and is more REST-like). The new APIs for assets and sensor data had already been working before (at /api/dev) and had been powering what is shown in the UI since v0.8.0.

We also implemented many CLI commands which support the new model (project 14).

We have deprecated and sunset all API versions before v3, while offering the ability for FlexMeasures hosts to organise blackout tests, and have removed the old database models (see project 11).

We take care to support people on the old data model so the transition will be as smooth as possible, as we said above. One part of this is that the ``flexmeasures db upgrade`` command copies your data to the new model. Also, creating new data (e.g. old-style assets) creates new-style data (e.g. assets/sensors) automatically. However, some edge cases are not supported in this way. For instance, edited asset meta data might have to be re-entered later. Feel free to contact us to discuss the transition if needed.
