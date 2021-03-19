.. _analytics:

****************
Client analytics
****************

The client analytics page shows relevant data to an asset's operation: production and consumption, market prices and weather data.
The view serves to browse through available data history and to assess how the app is monitoring and forecasting data streams from various sources.
In particular, the page contains:

.. contents::
    :local:
    :depth: 1


.. image:: https://github.com/SeitaBV/screenshots/raw/main/screenshot_analytics.png
    :align: center
..    :scale: 40%


.. _analytics_controls:

Data filtering
=============

FlexMeasures offers data analytics on various aggregation levels: per asset, per asset type or even per higher aggregation levels like all renewables.

The time window is freely selectable.

In addition, the source of market and weather data can be selected, as well as the forecast horizon.

For certain assets, which bundle meters on the same location, individual traces can be shown next to each other in the (upper left) power plot, for comparison.


.. _analytics_plots:

Data visualisation
==================

In each plot, the data is shown for different types of data: measurements (e.g. of power or prices), forecasts and schedules (only for power, obviously).

In the FlexMeasures platform, forecasting models can indicate a range of uncertainty around their forecasts, which will also be shown in plots if available. 


.. _analytics_metrics:

Metrics
==========

FlexMeasures summarises the visualised data as realised (by measurement) and expected (by forecast) sums.
In addition, the mean average error (MAE) and the weighted absolute percentage error (WAPE) are computed for power,
weather and price data if forecasts are available for the chosen time range.


