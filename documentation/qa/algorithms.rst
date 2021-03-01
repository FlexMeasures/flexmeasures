.. _algorithms:

What algorithms does the platform use?
==========================================


Forecasting
-----------

Forecasting algorithms are used by FlexMeasures to assess the likelihood of future consumption/production and prices.
Weather forecasting is included in the platform, but is not the result of an internal algorithm (see :ref:`weather`).
The performance of our algorithms is indicated by the mean absolute error (MAE) and the weighted absolute percentage error (WAPE).
Power profiles on an asset level often include zero values, such that the mean absolute percentage error (MAPE), a common statistical measure of forecasting accuracy, is undefined.
For such profiles, it is more useful to report the WAPE, which is also known as the volume weighted MAPE.
The MAE of a power profile gives an indication of the size of the uncertainty in consumption and production.
This allows the user to compare an asset's predictability to its flexibility, i.e. to the size of possible flexibility actions.

Example benchmarks per asset type are listed in the table below for various assets and forecasting horizons.
FlexMeasures updates the benchmarks automatically for the data currently selected by the user.
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

Defaults:

- The application uses an ordinary least squares auto-regressive model with external variables.
- Lagged outcome variables are selected based on the periodicity of the asset (e.g. daily and/or weekly).
- Common external variables are weather forecasts of temperature, wind speed and irradiation.
- Timeseries data with frequent zero values are transformed using a customised Box-Cox transformation.
- To avoid overfitting, cross-validation is used.
- Before fitting, explicit annotations of expert knowledge to the model (like the definition of asset-specific seasonalities and special time events) are possible.
- The model is currently fit each day for each asset and for each horizon.

Improvements:

- Most assets have yearly seasonalities (e.g. wind, solar) and therefore forecasts would benefit from >= 2 years of history.


Broker
------

A broker algorithm is used by the Aggregator to analyse flexibility in the Supplier's portfolio of assets, and to suggest the most valuable DR actions to take for each time slot.
The actions are presented to the Supplier as flexibility offers in the form of an order book.

Defaults:

-

Trading
-------

A trading algorithm is used to assist the Supplier with its decision-making across time slots, based on the order books made by the broker (see above).
The algorithm suggests which offers should be accepted next, and the Supplier may automate its decision-making by letting the algorithm place orders on its behalf.

Defaults:

- (Myopic greedy strategy) Order all flexibility with a positive expected value in the first available timeslot, then those in the second available timeslot, and so on.




Planning
--------

Based on decisions about control actions, a planning algorithm is used by the Aggregator (in case of explicit DR) or by the Energy Service Company (in case of implicit DR)
to form instructions for the Prosumer's flexible assets.

Defaults:

- 