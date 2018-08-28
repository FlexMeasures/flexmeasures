.. _algorithms:

What algorithms does the platform use?
==========================================


Forecasting
-----------

Forecasting algorithms are used by the Aggregator to assess the likelihood of future consumption/production and prices.
Weather forecasting is included in the platform, but is not the result of an internal algorithm (see :ref:`weather`).
The performance of our algorithms is indicated by the mean absolute error (MAE) and the weighted absolute percentage error (WAPE).
Power profiles on an asset level often include zero values, such that the mean absolute percentage error (MAPE), a common statistical measure of forecasting accuracy, is undefined.
For such profiles, it is more useful to report the WAPE, which is also known as the volume weighted MAPE.
The MAE of a power profile gives an indication of the size of the uncertainty in consumption and production.
This allows the user to compare an asset's predictability to its flexibility, i.e. to the size of possible balancing actions.

Benchmarks per asset type are listed below for various assets and forecasting horizons, given a 15-minute resolution:

+-------------------------+---------------+------------+---------------+----------------+-----------------+
| Asset                   | Building      | CS         | Solar         | Wind (offshore)| Day-ahead market|
+-------------------------+---------------+------------+---------------+----------------+-----------------+
| Average power per asset | 182 kW        | 75 W       | 1.4 MW        | 31.8 MW        |                 |
+=========================+===============+============+===============+================+=================+
| WAPE (1 hour ahead)     | 6.6 %         | - %        | 16.3 %        | 21.2 %         | 12.0 %          |
+-------------------------+---------------+------------+---------------+----------------+-----------------+
| WAPE (6 hours ahead)    | 7.4 %         | - %        | 46.4 %        | 101.8 %        | 18.1 %          |
+-------------------------+---------------+------------+---------------+----------------+-----------------+
| WAPE (24 hours ahead)   | 7.6 %         | - %        | 46.1 %        | 101.1 %        | 19.6 %          |
+-------------------------+---------------+------------+---------------+----------------+-----------------+
| WAPE (48 hours ahead)   | 7.9 %         | - %        | 43.3 %        | 100.9 %        | 27.7 %          |
+-------------------------+---------------+------------+---------------+----------------+-----------------+

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