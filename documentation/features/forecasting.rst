.. _forecasting:

Forecasting
============

Scheduling is about the future, and you need some knowledge / expectations about the future to do it.

In FlexMeasures, this knowledge often comes in the form of **forecasts** — data-driven estimates of what's likely to happen next.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/PV-forecasting-example.png
   :align: center

*Example of a 24-hour horizon forecast for solar power production.*

Of course, the nicest forecasts are the ones you don't have to make yourself (it's not an easy field), so do use price or usage forecasts from third parties if available, and load them into FlexMeasures.
There are even existing plugins for importing `weather forecasts <https://github.com/flexmeasures/flexmeasures-weather>`_ or `market data <https://github.com/SeitaBV/flexmeasures-entsoe>`_.

If you need to make your own predictions, forecasting algorithms can be used within FlexMeasures, for instance, to arrive at an expected profile of future solar power production at the site.

FlexMeasures provides a CLI command and an API endpoint to generate forecasts (see below).

FlexMeasures provides a **fixed viewpoint forecasting infrastructure**.
This means that from one point in time (the fixed viewpoint), we forecast a range of events into the future (e.g. 24 hourly events for a span of one day). While the first forecast (one hour ahead) has a small horizon (1H), the last one has a large horizon (24H) and the accuracy between the two will usually differ (it is easier to forecast small horizons).

At the same time, the design we implemented in FlexMeasures is inspired by **rolling forecasts**, as training and prediction can be repeated in **cycles** until a user-specified end date is reached.  If you ask FlexMeasures for a fixed viewpoint forecast (one cycle), the model is trained once on the most recent applicable historical period and then produces predictions for the requested future period in one go.
This is controlled by the ``forecast-frequency`` parameter, which specifies how often predictions are generated during the forecast period.

How a forecasting cycle works
-------------

A single forecasting cycle consists of the following steps:

1. **Training**: Fit the model on a historical window defined by ``train-start`` and ``train-end``.
2. **Prediction**: Produce forecasts for a time window defined by ``predict-start`` and ``predict-end``.
3. **Repeat**: Extend the training window and move the prediction window forward, both by ``forecast-frequency``.

Cycles repeat until ``predict-end`` reaches the global ``to-date``.
This way, forecasts can cover long ranges while still being based on updated training data in each cycle.

CLI Command
--------------
You can create forecasts from the command line using:

.. code-block:: bash

    flexmeasures add forecasts --from-date 2024-02-02 --to-date 2024-02-02 --max-forecast-horizon 6 --sensor 12 --as-job

This command asks FlexMeasures to generate forecasts for one day (2 February 2024)
with a forecast horizon of 6 hours for the sensor with ID 12.
If you include ``--as-job``, the forecasting task is added to the job queue to be processed by a worker.

The main CLI parameters that control this process are:

- ``from-date``: Defines the first ``predict-start``.
- ``to-date``: The global cutoff point. Training and prediction cycles continue until the ``predict-end`` reaches this date.
- ``max-forecast-horizon``: The maximum length of a forecast into the future.
- ``forecast-frequency``: Determines the number of prediction cycles within the forecast period (e.g. daily, hourly).
- ``start-date``: Define the start of historical data used for training.

Note that:

``forecast-frequency`` together with ``max-forecast-horizon`` determine how the forecasting cycles advance through time.
``start-date`` / ``from-date`` and ``to-date`` allow precise control over the training and prediction windows in each cycle.

Forecasting via the API
-----------------------

In addition to the CLI command, FlexMeasures provides API endpoints for
triggering forecasts and retrieving their results.

These endpoints live under the Sensor API (``/api/v3_0/sensors``).

Triggering a forecast
^^^^^^^^^^^^^^^^^^^^^

.. http:post:: /api/v3_0/sensors/<id>/forecasts/trigger

   Launch a forecasting job asynchronously for the given sensor.

   .. note:: To use this endpoint, you need the  ``create-children`` permission on the sensor (meaning you should be in the same account or be a consultant on it).

   **Request JSON:**

   .. code-block:: json

       {
         "start_date": "2025-01-01T00:00:00+00:00",
         "start_predict_date": "2025-01-04T00:00:00+00:00",
         "end_date": "2025-01-04T04:00:00+00:00"
       }

   **Response (200):**

   .. code-block:: json

       {
         "status": "PROCESSED",
         "forecast": "b3d26a8a-7a43-4a9f-93e1-fc2a869ea97b",
         "message": "Forecast job has been queued."
       }

   This endpoint will queue a background job on the forecasting queue.

Checking job status & retrieving forecasts
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. http:get:: /api/v3_0/sensors/<id>/forecasts/<uuid>

   Retrieve the status of a forecasting job and, if it finished, its forecast data.

   **Permissions:** ``read`` on the sensor.

   **Response when running:**

   .. code-block:: json

       {
         "status": "RUNNING",
         "job_id": "<uuid>"
       }

   **Response when finished (200):**

   .. code-block:: json

       {
         "status": "FINISHED",
         "job_id": "<uuid>",
         "sensor": 12,
         "forecasts": {
           "2025-01-04T00:15:00+00:00": [
             {
               "event_start": "2025-01-04T00:15:00+00:00",
               "belief_time": "2025-01-04T00:00:00+00:00",
               "cumulative_probability": 0.5,
               "value": 3.27
             },
             ...
           ]
         }
       }

   The returned forecasts are grouped by event start time. Only the most recent belief for each event is returned, matching the behavior of ``sensor.search_beliefs(..., most_recent_beliefs_only=True)``.

Technical specs
-----------------

In a nutshell, FlexMeasures uses a LightGBM regression model (``darts.models.LightGBMModel``) as its base model to forecast future values.

Note that the most important factor is often the features provided to the model ― lagged values (e.g., the value at the same time yesterday) and regressors (e.g., wind speed prediction to forecast wind power production).  
Most assets have yearly seasonality (e.g. wind, solar) and therefore forecasts benefit from at least two years of historical data.

Here are more details:

- The main model is a LightGBM model, which can be wrapped to produce probabilistic forecasts if required.
- Lagged outcome variables are selected based on the periodicity of the asset (e.g. hourly, daily and/or weekly).
- Missing data is filled using linear interpolation (via the Darts ``MissingValuesFiller``, which wraps ``pandas.DataFrame.interpolate``).
- The model is trained once per cycle for each asset and can forecast up to the maximum forecast horizon in a single run.
- Forecasts are **fixed viewpoint forecasts** — the model is trained on a given history and produces predictions for a future window in one go.
  Training and prediction can then be repeated in **cycles** until a user-specified end date is reached.  
  This cycle-based design is inspired by rolling forecasts while keeping a fixed viewpoint.  
  The ``forecast-frequency`` parameter controls how often predictions are generated during the forecast period.
A use case: automating solar production prediction
-----------------------------------------------------

We'll consider an example that FlexMeasures supports ― forecasting an asset that represents solar panels.
Here is how you can ask for forecasts to be made in the CLI:

.. code-block:: bash

    flexmeasures add forecasts --from-date 2024-02-02 --to-date 2024-02-02 --max-forecast-horizon 6 --sensor 12  --as-job  # add train-start

Sensor 12 would represent the power readings of your solar power, and here you ask for forecasts for one day (2 February, 2024), with a forecast of 6 hours.

The ``--as-job`` parameter is optional. If given, the computation becomes a job which a worker needs to pick up. There is some more information at :ref:`how_queue_forecasting`.


Fixed viewpoint vs rolling viewpoint
------------------------------------

Unlike previous rolling forecasts, where each prediction covers the same relative forecast horizon (but the origin keeps moving forward), the new infrastructure generates **fixed viewpoint forecasts**:

- One reference timestamp.
- Predictions are made for multiple future horizons from that point.
- Periodic retraining ensures forecasts remain accurate.

Regressors
-------------

If you want to take regressors into account, in addition to merely past measurements (e.g. weather forecasts, see above).

- past regressors : sensors that only have realizations (historical data).
- future regressors : sensors that only have forecasts (e.g. weather forecasts).
- regressors : sensors that have both historical data and forecasts (e.g. weather forecasts).

Including regressors can significantly improve forecasting accuracy, especially when they are highly correlated with the target variable. For example, using irradiation forecasts as regressors can substantially improve solar production predictions.
In `this weather forecast plugin <https://github.com/flexmeasures/flexmeasures-weather>`_, we enable you to collect regressor data for ``["temperature", "wind speed", "cloud cover", "irradiance"]``, at a location you select.

