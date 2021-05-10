.. _algorithms:


Algorithms
==========================================

.. contents::
    :local:
    :depth: 2


.. _algorithms_forecasting:

Forecasting
-----------

Forecasting algorithms are used by FlexMeasures to assess the likelihood of future consumption/production and prices.
Weather forecasting is included in the platform, but is usually not the result of an internal algorithm (weather forecast services are being used by import scripts, e.g. with `this tool <https://github.com/SeitaBV/weatherforecaststorage>`_).

FlexMeasures uses linear regression and falls back to naive forecasting of the last known value if errors happen. 
What might be even more important than the type of algorithm is the features handed to the model ― lagged values (e.g. value of the same time yesterday) and regressors (e.g. wind speed prediction to forecast wind power production).


The performance of our algorithms is indicated by the mean absolute error (MAE) and the weighted absolute percentage error (WAPE).
Power profiles on an asset level often include zero values, such that the mean absolute percentage error (MAPE), a common statistical measure of forecasting accuracy, is undefined.
For such profiles, it is more useful to report the WAPE, which is also known as the volume weighted MAPE.
The MAE of a power profile gives an indication of the size of the uncertainty in consumption and production.
This allows the user to compare an asset's predictability to its flexibility, i.e. to the size of possible flexibility activations.

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
- To avoid over-fitting, cross-validation is used.
- Before fitting, explicit annotations of expert knowledge to the model (like the definition of asset-specific seasonality and special time events) are possible.
- The model is currently fit each day for each asset and for each horizon.

Improvements:

- Most assets have yearly seasonality (e.g. wind, solar) and therefore forecasts would benefit from >= 2 years of history.


.. _algorithms_scheduling:

Scheduling 
------------

Given price conditions or other conditions of relevance, a scheduling algorithm is used by the Aggregator (in case of explicit DR) or by the Energy Service Company (in case of implicit DR) to form a recommended schedule for the Prosumer's flexible assets.


Storage devices
^^^^^^^^^^^^^^^

So far, FlexMeasures provides algorithms for storage ― for batteries (e.g. home batteries or EVs) and car charging stations.
We thus cover the asset types "battery", "one-way_evse" and "two-way_evse".

These algorithms schedule the storage assets based directly on the latest beliefs regarding market prices, within the specified time window.
They are mixed integer linear programs, which are configured in FlexMeasures and then handed to a dedicated solver.

For all scheduling algorithms, a starting state of charge (SOC) as well as a set of SOC targets can be given. If no SOC is available, we set the starting SOC to 0. 

Also, per default we incentivise the algorithms to prefer scheduling charging now rather than later, and discharging later rather than now.
We achieve this by adding a tiny artificial price slope. We penalise the future with at most 1 per thousand times the price spread. This behaviour can be turned off with the `prefer_charging_sooner` parameter set to `False`.

.. note:: For the resulting consumption schedule, consumption is defined as positive values.
    

Possible future work on algorithms
-----------------------------------

Enabling more algorithmic expression in FlexMeasures is crucial. This are a few ideas for future work. Some of them are excellent topics for Bachelor or Master theses. so get in touch if that is of interest to you.

More configurable forecasting
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
On the roadmap for FlexMeasures is to make features easier to configure, especially regressors.
Furthermore, we plan to add more types of forecasting algorithms, like random forest or even LSTM.


Other optimisation goals for scheduling
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Next to market prices, optimisation goals like reduced CO₂ emissions are sometimes required. There are multiple ways to measure this, e.g. against the CO₂ mix in the grid, or the use of fossil fuels.


Scheduling of other flexible asset types
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Next to storage, there are other interesting flexible assets which can require specific implementations.
For shifting, there are heat pumps and other buffers. For curtailment, there are wind turbines and solar panels.

.. note:: See :ref:`flexibility_types` for more info on shifting and curtailment.

Broker algorithm
^^^^^^^^^^^^^^^^^
A broker algorithm is used by the Aggregator to analyse flexibility in the Supplier's portfolio of assets, and to suggest the most valuable flexibility activations to take for each time slot.
The differences to single-asset scheduling are that these activations are based on a helicopter perspective (the Aggregator optimises a portfolio, not a single asset) and that the flexibility offers are presented to the Supplier in the form of an order book.


Trading algorithm
^^^^^^^^^^^^^^^^^^
A trading algorithm is used to assist the Supplier with its decision-making across time slots, based on the order books made by the broker (see above).
The algorithm suggests which offers should be accepted next, and the Supplier may automate its decision-making by letting the algorithm place orders on its behalf.

A default approach would be a myopic greedy strategy ― order all flexibility opportunities with a positive expected value in the first available timeslot, then those in the second available timeslot, and so on.
