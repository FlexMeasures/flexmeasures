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
- ``train-period``: Define a window of historical data to use for training.

Note that:

``forecast-frequency`` together with ``max-forecast-horizon`` determine how the forecasting cycles advance through time.
``train-period``, ``from-date`` and ``to-date`` allow precise control over the training and prediction windows in each cycle.

Forecast post-processing
--------------------------------

Forecaster configuration can clip and snap forecast values before they are stored.
Use ``lower`` and ``upper`` to clip values to bounds, and ``snap`` to replace values inside a configured interval with a target value.
Units are optional; unitless values are interpreted in the output sensor unit.

For example, this configuration clips forecasts to the 0-20 kW range and snaps values in ``[0 kW, 4 kW)`` to 0 kW:

.. code-block:: json

    {
      "lower": "0 kW",
      "snap": {
        "0 kW": ["0 kW", "4 kW"]
      },
      "upper": "20 kW"
    }

The snap target must lie within its interval (on a bound or inside it), so values never snap to a value outside the interval. A target inside the interval snaps the whole band to that value, for example ``{"2 kW": ["0 kW", "4 kW"]}`` snaps everything in ``[0 kW, 4 kW)`` to 2 kW.
The first bound is inclusive and the second is exclusive, so an interval reads as ``[first, second)``.
Listing the bounds in reverse order flips the closed side: ``["10 kW", "4 kW"]`` means ``(4 kW, 10 kW]``.
This keeps adjacent intervals unambiguous — a value on a shared boundary belongs to the interval that opens at it.
For instance, given ``{"0 kW": ["0 kW", "4 kW"], "10 kW": ["4 kW", "10 kW"]}``, a forecast of exactly 4 kW snaps to 10 kW.

Snapping runs first and clipping runs afterwards, so ``lower``/``upper`` always take precedence: a snap target outside the bounds is clipped back into range.

Pass the same object as the API ``config`` payload, or place it in a JSON or YAML file and pass it to ``flexmeasures add forecasts`` with ``--config``.

Cleaning the data a forecaster trains on
-----------------------------------------

The bounds above shape the forecast on its way out. The same ``lower``, ``upper`` and ``snap`` fields can also be set on an individual regressor or on the target, where they clean that sensor's readings on the way *in*, before the model trains on them.
This is for a sensor whose recorded data is not trustworthy as it stands — an occasional implausible spike, or an error sentinel such as ``-9999`` — that you would rather not have to correct upstream.

Put the bounds on the sensor reference itself. A bare sensor ID keeps working, and so does a reference that only filters by source. In the forecaster config, alongside the regressors:

.. code-block:: json

    {
      "past-regressors": [
        2094,
        {"sensor": 2095, "lower": "0 kW", "snap": {"0 kW": ["0 kW", "0.5 kW"]}}
      ]
    }

The target is named in the forecast parameters rather than the config, so its bounds go there:

.. code-block:: json

    {
      "sensor": {"sensor": 2092, "upper": "20 kW"}
    }

Each sensor's bounds are read in that sensor's own unit, not the unit of the sensor being forecast, so a regressor recording watts takes its bounds in watts unless you say otherwise.
Snapping and clipping behave exactly as they do on the output, including the ``[first, second)`` interval rule described above.

Three things are worth knowing before relying on this:

- Input bounds and output bounds are configured separately and may disagree. Cleaning the target's training data does not bound the forecast that comes out of it, and vice versa.
- The bounds are part of the general sensor reference, so a flex-model or flex-context reference takes them too, and the scheduler cleans the readings it takes from that sensor in the same way.
- Bounding runs **after** missing values are filled, so a value interpolated across a gap is bounded too. It also means an out-of-range reading is still used to interpolate its neighbours before it is itself corrected: given readings of ``10``, ``-9999``, a gap, and ``14`` with ``lower: 0``, the gap interpolates from ``-9999`` and is then clipped to ``0``, rather than filling to roughly ``12``. Where readings are wrong rather than merely out of range, correcting them at the source is still the better fix.

Forecasting via the UI
-----------------------

The quickest way to create a one-off forecast is the **Create forecast** button on the sensor page (see :ref:`view_sensors_forecast_button`). The button is available to users with permission to record data on sensors, provided at least two days of historical data exist. The forecast duration defaults to 48 hours (configured via ``FLEXMEASURES_PLANNING_HORIZON``) but can be adjusted up to 7 days in the panel. No further configuration is needed — one click queues the job and the page shows progress messages until the forecast is ready.

For more control over what and how to forecast, use the API.

Forecasting via the API
-----------------------

In addition to the CLI command, FlexMeasures provides API endpoints for triggering forecasts and retrieving their results.

These endpoints live under the Sensor API (``/api/v3_0/sensors``).

A typical workflow is:

1. Trigger a forecasting job for a sensor.
2. Poll the job until it finishes.
3. Retrieve the forecast results.

For the exact API endpoints, parameters, and response formats, refer to the API v3 documentation:

- `[POST] /sensors/(id)/forecasts/trigger <api/v3_0.html#post--api-v3_0-sensors-id-forecasts-trigger>`_
- `[GET] /sensors/(id)/forecasts/(uuid) <api/v3_0.html#get--api-v3_0-sensors-id-forecasts-uuid>`_

or try the endpoints interactively with the Swagger UI at ``/api/v3_0/docs``.

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

Choosing which data sources to train on
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Where several data sources record on the same sensor, you can say which of them the forecaster should read.
Anywhere a sensor ID is accepted — the three regressor options, and the target sensor itself — you can pass a *sensor reference* instead: a small object naming the sensor plus the source filters to apply to it.

- ``sources``: only use beliefs from these data source IDs.
- ``source-types``: only use beliefs from sources of these types, e.g. ``"user"``, ``"script"``, ``"forecaster"`` or ``"scheduler"``.
- ``exclude-source-types``: leave out beliefs from sources of these types.
- ``source-account``: only use beliefs from sources belonging to these accounts.

When a reference lists multiple sources, the first listed source wins if two of them hold beliefs about the same event, recorded at the same time.

.. code-block:: bash

    flexmeasures add forecasts \
      --sensor '{"sensor": 42, "sources": [12]}' \
      --regressors '{"sensor": 43, "exclude-source-types": ["forecaster"]}'

Here the model is trained on the readings that source 12 recorded on sensor 42, and ignores whatever else was recorded there.

.. note::

   A target given as a bare sensor ID is trained on every source recording on it, except forecasters, which are left out so that the forecaster does not learn from its own forecasts.
   A reference replaces that default entirely, so add ``"exclude-source-types": ["forecaster"]`` yourself if you want forecasters kept out alongside another filter.

Forecasts are always recorded on the sensor itself, never on a source-filtered view of it, so the source filters on a target only say what to train on.
Over the API, the target sensor is named by the URL of the trigger endpoint, so references there apply to regressors only.

Annotation regressors
~~~~~~~~~~~~~~~~~~~~~

In addition to sensor-based regressors, you can use *annotation regressors* to let the forecasting model learn from binary signals derived from annotation data. Holiday flags, factory shutdowns, or any other event stored as an annotation can be passed as future covariates.

Annotation regressors are configured in the ``annotation-regressors`` key of the forecasting config. Each entry is a dict with:

- ``account``, ``asset``, or ``sensor`` (required): the database ID of the account, asset, or sensor whose annotations to use.
- ``annotation-type`` (optional, default ``"holiday"``): filter to annotations of this type (``"holiday"``, ``"label"``, ``"alert"``, etc.).
- ``name`` (optional): a human-readable column name for the regressor. Defaults to ``annotation_regressor_<index>``.

The annotation data is converted to a binary 0/1 time series at the target sensor's resolution: **1** for every time step that falls within an annotation period, **0** otherwise. Since holidays and scheduled events are typically known in advance, annotation regressors are treated as *future* covariates.

Example config (passed via ``--config`` file):

.. code-block:: json

    {
      "annotation-regressors": [
        {"account": 1, "annotation-type": "holiday", "name": "public_holidays"},
        {"asset": 5, "annotation-type": "label", "name": "factory_shutdown"}
      ]
    }

Usage:

.. code-block:: bash

    flexmeasures add forecasts \
      --from-date 2024-01-01T00:00:00+00:00 \
      --to-date 2024-12-31T00:00:00+00:00 \
      --max-forecast-horizon PT24H \
      --sensor 42 \
      --annotation-regressors \
        '{"account": 1, "annotation-type": "holiday", "name": "public_holidays"}'

.. note::

   Create the annotations you want to use as regressors before running the forecast.
   For holidays, use ``flexmeasures add holidays``, which supports both ``workalendar``
   and ``holidays``. See :ref:`annotations` for details.

.. _automating_forecasts:

Automating forecasts
--------------------

Instead of asking for forecasts one at a time, you can set up an *automation*: a recurring task defined on an asset, which queues forecasting jobs on a cron schedule.
See :ref:`automations`.
Schedules can be automated in the same way — see :ref:`automating_schedules`.
