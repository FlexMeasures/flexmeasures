.. |check_| raw:: html

    <input checked=""  disabled="" type="checkbox">

.. |uncheck_| raw:: html

    <input disabled="" type="checkbox">

.. _note_on_datamodel_transition:

A note on the ongoing data model transition
============================================

FlexMeasures is already ~3 years in the making. It's a normal process for well-maintained software to update architectural principles during such a time.

We are in the middle of a refactoring which affects the data model, and if you are using FlexMeasures on your own server, we want you to know the following:
    

We have your back
------------------

If you work with the current model, there will be support to transition data to the new model once it's active. Actually, we are already working with the new model in some projects, so talk to us if you're interested.


This transition is in your interest, as well
----------------------------------------------

We do this transition so we can make FlexMeasures even more useful. For instance: support for more kinds of assets (energy plus related sensors). Or better forecasting and scheduling support.


What are the big changes?
-----------------------------

There are two important transitions happening in this transition:

1. First, we'll be deprecating the specific data types ``Asset``, ``Market`` and ``WeatherSensor``. We learned that to manage energy flexibility, you need all sort of sensors, and thus a more generalisable data model. When we model assets and sensors, we'll also better be able to differentiate the business from the data world.
2. Second, we'll fully integrate the `timely-beliefs framework <https://github.com/SeitaBV/timely-beliefs>`_ as the model for our time series data, which brings some major benefits for programmers as it lets us handle uncertain, multi-source time series data in a special Pandas data frame.

For the curious, here are visualisations of where we're now and where we're going (click image for large versions).

The current model:

.. image:: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/FlexMeasures-CurrentDataModel.png
    :target: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/FlexMeasures-CurrentDataModel.png
    :align: center
..    :scale: 40%

The new model (work in progress): 

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
- |uncheck_| `Update API endpoints for time series communication <https://github.com/FlexMeasures/flexmeasures/projects/13>`_: We are updating our API with new endpoints for communicating time series data, thereby consolidating a few older endpoints into a better standard. We do this so we can both simplify our API and documentation, and support a diversity of sensors.
- |uncheck_| `Update CLI commands for setting up Sensors and Assets <https://github.com/FlexMeasures/flexmeasures/projects/14>`_: We are updating our CLI commands to reflect the new database structure. We do this to facilitate setting up structure for new users.
- |uncheck_| `Update UI views for Sensors and Assets <https://github.com/FlexMeasures/flexmeasures/projects/10>`_: We are updating our UI views (dashboard maps and analytics charts) according to our new database structure for organising energy data. We do this so users can customize what they want to see.
- |uncheck_| `Scheduling of sensors <https://github.com/FlexMeasures/flexmeasures/projects/6>`_: We are extending our database structure for Sensors with actuator functionality, and are moving to a model store where scheduling models can be registered. We do this so we can provide better plugin support for scheduling a diverse set of devices.
- |uncheck_| `Forecasting of sensors <https://github.com/FlexMeasures/flexmeasures/projects/8>`_: We are revising our forecasting tooling to support fixed-viewpoint forecasts. We do this so we can better support decision moments with the most recent expectations about relevant sensors.
- |uncheck_| `Deprecate old database models <https://github.com/FlexMeasures/flexmeasures/projects/11>`_: We are deprecating the Power, Price and Weather tables in favour of the TimedBelief table, and deprecating the Asset, Market and WeatherSensor tables in favour of the Sensor and GeneralizedAsset tables. We are doing this to clean up the code and database structure.


The state of the transition (January 2022, v0.8.0)
---------------------------------------------------

Project 9 was implemented, which moved a lot of structure over, as well as actual data and some UI (dashboard, assets). We believe that was the hardest part.

We are now close to being able to deprecate the old database models and route the API to the new model (see project 11). The API for assets is still in place, but the new one is already working (at /api/dev/generic_assets) and is powering what is shown in the UI.

We take care to support people on the old data model so the transition will be as smooth as possible, as we said above. One part of this is that the ``flexmeasures db upgrade`` command copies your data to the new model. Also, creating new data (e.g. old-style assets) creates new-style data (e.g. assets/sensors) automatically. However, some edge cases are not supported in this way. For instance, edited asset meta data might have to be re-entered later. Feel free to contact us to discuss the transition if needed.
