.. _forecasting:

Forecasting
============

Scheduling is about the future, and you need some knowledge / expectations about the future to do it.

Of course, the nicest forecasts are the one you don't have to make yourself (it's not an easy field), so do use price or usage forecasts from third parties if available.
There are even existing plugins for importing `weather forecasts <https://github.com/flexmeasures/flexmeasures-weather>`_ or `market data <https://github.com/SeitaBV/flexmeasures-entsoe>`_.

If you need to make your own predictions, forecasting algorithms can be used within FlexMeasures, for instance to assess the expected profile of future consumption/production.

FlexMeasures provides a **fixed-view forecasting infrastructure**.  
This means that the model is trained once on a historical period and then produces predictions for a future period in one go.  

At the same time, the design is inspired by **rolling forecasts**, as training and prediction can be repeated in **cycles** until a user-specified end date is reached.  
This is controlled by the ``forecast_frequency`` parameter, which specifies how often predictions are generated during the forecast period.

Cycle Example
-------------

A single forecasting cycle consists of the following steps:

1. **Training**: Fit the model on a historical window defined by ``train_start`` and ``train_end``.  
2. **Prediction**: Produce forecasts for a horizon defined by ``predict_start`` and ``predict_end``.  
3. **Repeat**: If the global ``end_date`` is not yet reached, move the prediction window forward by ``forecast_frequency`` and repeat steps 1 and 2.

This way, forecasts can cover long ranges while still being based on updated training data in each cycle.

CLI Parameters
--------------

The main CLI parameters that control this process are:

- ``start-date``: Define the start of historical data used for training.  
- ``from_date``: Define the period for which forecasts are generated.  
- ``forecast_frequency``: How often predictions are generated within the forecast period (e.g. daily, hourly).  
- ``max_forecast_horizon``: The maximum length of a forecast into the future.  
- ``to_date``: The global cutoff point. Training and prediction cycles continue until this date is reached.

``forecast_frequency`` together with ``max_forecast_horizon`` determine how the forecasting cycles advance through time.  
``start-date`` / ``from_date`` and ``to_date`` allow precise control over the training and prediction windows in each cycle.

Technical specs
-----------------

In a nutshell, FlexMeasures uses linear regression and falls back to naive forecasting of the last known value if errors happen. 

Note that what might be even more important than the type of algorithm is the features handed to the model ― lagged values (e.g. value of the same time yesterday) and regressors (e.g. wind speed prediction to forecast wind power production).
Most assets have yearly seasonality (e.g. wind, solar) and therefore forecasts would benefit from >= 2 years of history.

Here are more details:

- The application uses an ordinary least squares auto-regressive model with external variables.
- Lagged outcome variables are selected based on the periodicity of the asset (e.g. daily and/or weekly).
- Common external variables are weather forecasts of temperature, wind speed and irradiation.
- Timeseries data with frequent zero values are transformed using a customised Box-Cox transformation.
- To avoid over-fitting, cross-validation is used.
- Before fitting, explicit annotations of expert knowledge to the model (like the definition of asset-specific seasonality and special time events) are possible.
- The model is currently fit each day for each asset and for each horizon.


A use case: automating solar production prediction
-----------------------------------------------------

We'll consider an example that FlexMeasures supports ― forecasting an asset that represents solar panels.
Here is how you can ask for forecasts to be made in the CLI:

.. code-block:: bash

    flexmeasures add forecasts --from-date 2024-02-02 --to-date 2024-02-02 --horizon 6 --sensor 12  --as-job

Sensor 12 would represent the power readings of your solar power, and here you ask for forecasts for one day (2 February, 2024), with a forecast of 6 hours.

The ``--as-job`` parameter is optional. If given, the computation becomes a job which a worker needs to pick up. There is some more information at :ref:`how_queue_forecasting`.


Rolling vs fixed-point
-------------------------

These forecasts are `rolling` forecasts ― which means they all have the same horizon. This is useful mostly for analytics and simulations.

We plan to work on fixed-point forecasts, which would forecast all values from one point in time, with a growing horizon as the forecasted time is further away.
This resembles the real-time situation better.


Regressors
-------------

If you want to take regressors into account, in addition to merely past measurements (e.g. weather forecasts, see above),
currently FlexMeasures supports only weather correlations.

The attribute `sensor.weather_correlations` can be used for this, e.g. for the solar example above you might want to set this to ``["irradiance", "temperature"]``.
FlexMeasures will then try to find an asset with asset type "weather_station" that has a location near the asset your forecasted sensor belogs to.
That weather station should have sensors with the correlations you entered, and if they have data in a suitable range, the regressors can be used in your forecasting.

In `this weather forecast plugin <https://github.com/flexmeasures/flexmeasures-weather>`_, we enable you to collect regressor data for ``["temperature", "wind speed", "cloud cover", "irradiance"]``, at a location you select.


Performance benchmarks
-----------------------

Above, we focused on technical ways to achieve forecasting within FlexMeasures. As we mentioned, the results differ, based on what information you give to the model.

However, let's discuss performance a little more ― how can we measure it and what have we seen?
The performance of FlexMeasures' forecasting algorithms is indicated by the mean absolute error (MAE) and the weighted absolute percentage error (WAPE).
Power profiles on an asset level often include zero values, such that the mean absolute percentage error (MAPE), a common statistical measure of forecasting accuracy, is undefined.
For such profiles, it is more useful to report the WAPE, which is also known as the volume weighted MAPE.
The MAE of a power profile gives an indication of the size of the uncertainty in consumption and production.
This allows the user to compare an asset's predictability to its flexibility, i.e. to the size of possible flexibility activations.

Example benchmarks per asset type are listed in the table below for various assets and forecasting horizons.
Amongst other factors, accuracy is influenced by:

- The chosen metric (see below)
- Resolution of the forecast
- Horizon of the forecast
- Asset type
- Location / Weather conditions
- Level of aggregation

Accuracies in the table are reported as 1 minus WAPE, which can be interpreted as follows:

- 100% accuracy denotes that all values are correct.
- 50% accuracy denotes that, on average, the values are wrong by half of the reference value.
- 0% accuracy denotes that, on average, the values are wrong by exactly the reference value (i.e. zeros or twice the reference value).
- negative accuracy denotes that, on average, the values are off-the-chart wrong (by more than the reference value itself).


+---------------------------+---------------+---------------+---------------+-----------------+-----------------+
| Asset                     | Building      | Charge Points | Solar         | Wind (offshore) | Day-ahead market|
+---------------------------+---------------+---------------+---------------+-----------------+-----------------+
| Average power per asset   | 204 W         | 75 W          | 140 W         | 518 W           |                 |
+===========================+===============+===============+===============+=================+=================+
| 1 - WAPE (1 hour ahead)   | 93.4 %        | 87.6 %        | 95.2 %        | 81.6 %          | 88.0 %          |
+---------------------------+---------------+---------------+---------------+-----------------+-----------------+
| 1 - WAPE (6 hours ahead)  | 92.6 %        | 73.0 %        | 83.7 %        | 73.8 %          | 81.9 %          |
+---------------------------+---------------+---------------+---------------+-----------------+-----------------+
| 1 - WAPE (24 hours ahead) | 92.4 %        | 65.2 %        | 46.1 %        | 60.1 %          | 81.4 %          |
+---------------------------+---------------+---------------+---------------+-----------------+-----------------+
| 1 - WAPE (48 hours ahead) | 92.1 %        | 63.7 %        | 43.3 %        | 56.9 %          | 72.3 %          |
+---------------------------+---------------+---------------+---------------+-----------------+-----------------+


Future work
---------------

We have mentioned that forecasting within FlexMeasures can become more powerful.
Here we summarize what is on the roadmap for forecasting:

- Add fixed-point forecasting (see above)
- Make features easier to configure, especially regressors
- Add more types of forecasting algorithms, like random forest or even LSTM
- Possibly integrate with existing powerful forecasting tooling, for instance `OpenStef <https://lfenergy.org/projects/openstef>`_ or `Quartz Solar OS <https://github.com/openclimatefix/Open-Source-Quartz-Solar-Forecast>`_. 


