.. _algorithms:

What algorithms does the VPP platform use?
==========================================


Forecasting
-----------

A forecasting algorithm is used by the Aggregator to assess the likelihood of future loads and prices. Weather forecasting is included in the VPP platform, but is not the result of an internal algorithm (see :ref:`weather` ).

Defaults:

- The application uses a decomposable time series model. For fitting curve parameters, we employ a Limited-memory BFGS algorithm. To avoid overfitting, cross-validation is used.
- Before fitting, explicit annotations of expert knowledge to the model (like the definition of asset-specific seasonalities and special time events) are possible.
- The model is currently fit once for each asset.

Improvements:

- Fit the model each 15 minutes (rolling horizon)
- Allow the expert to set upper and lower limits for the data
- Some assets have yearly seasonalities (e.g. wind, solar) and therefore forecasts would benefit from >= 2 years of history.
- Also, forecasts in the app right now are in-sample forecasts, using nothing but the actual values as input to the forecasting problem. Some additional data, e.g. weather forecasts, can improve the asset forecasts.


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