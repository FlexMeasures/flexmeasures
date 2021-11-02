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

We do this transition so we can make FlexMeasures even more useful. Support for more kinds of assets (energy plus related). Better forecasting support.


What is going on in detail?
-----------------------------

The most important transition is that we'll be deprecating the specific data types ``Asset``, ``Market`` and ``WeatherSensor``. We learned that to manage energy flexibility, you need all sort of sensors.

Furthermore, we'll fully integrate the `timely-beliefs framework <https://github.com/SeitaBV/timely-beliefs>`_ as as the model for our time series data , which brings some major benefits for programmers as it lets us handle uncertain, multi-source time series data in a special Pandas data frame. See `the respective Github project <https://github.com/SeitaBV/flexmeasures/projects/3>`_ for the roadmap, where we'll also deprecate the aforementioned data types.

Lastly, we'll give the concepts of forecasting and scheduling a re-design (project 6) to be more flexible and useful, which can also affect the API. See `the respective Github project <https://github.com/SeitaBV/flexmeasures/projects/6>`_ for this roadmap.

For the curious, here are visualisations of where we're now and where we're going (click image for large versions).

The current model:

.. image:: https://raw.githubusercontent.com/SeitaBV/screenshots/main/architecture/FlexMeasures-CurrentDataModel.png
    :target: https://raw.githubusercontent.com/SeitaBV/screenshots/main/architecture/FlexMeasures-CurrentDataModel.png
    :align: center
..    :scale: 40%

The new model (work in progress): 

.. image:: https://raw.githubusercontent.com/SeitaBV/screenshots/main/architecture/FlexMeasures-NewDataModel.png
    :target: https://raw.githubusercontent.com/SeitaBV/screenshots/main/architecture/FlexMeasures-NewDataModel.png
    :align: center
..    :scale: 40%
