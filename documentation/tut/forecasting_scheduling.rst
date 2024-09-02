.. _tut_forecasting_scheduling:

Forecasting & scheduling
========================

Once FlexMeasures contains data (see :ref:`tut_posting_data`), you can enjoy its forecasting and scheduling services.
Let's take a look at how FlexMeasures users can access information from these services, and how you (if you are hosting FlexMeasures yourself) can set up the data science queues for this.

.. contents:: Table of contents
    :local:
    :depth: 1

If you want to learn more about the actual algorithms used in the background, head over to :ref:`scheduling` and :ref:`forecasting`.

.. note:: FlexMeasures comes with in-built scheduling algorithms. You can use your own algorithm, as well, see :ref:`plugin-customization`.


Maintaining the queues
------------------------------------

.. note:: If you are not hosting FlexMeasures yourself, skip right ahead to :ref:`how_queue_forecasting` or :ref:`getting_prognoses`.

Here we assume you have access to a Redis server and configured it (see :ref:`redis-config`).

Start to run one worker for each kind of job (in a separate terminal):

.. code-block:: bash

   $ flexmeasures jobs run-worker --queue forecasting
   $ flexmeasures jobs run-worker --queue scheduling


You can also clear the job queues:

.. code-block:: bash

   $ flexmeasures jobs clear-queue --queue forecasting
   $ flexmeasures jobs clear-queue --queue scheduling


When the main FlexMeasures process runs (e.g. by ``flexmeasures run``\ ), the queues of forecasting and scheduling jobs can be visited at ``http://localhost:5000/tasks/forecasting`` and ``http://localhost:5000/tasks/schedules``\ , respectively (by admins).

When forecasts and schedules have been generated, they should be visible at ``http://localhost:5000/assets/<id>``.


.. note:: You can run workers who process jobs on different computers than the main server process. This can be a great architectural choice. Just keep in mind to use the same databases (postgres/redis) and to stick to the same FlexMeasures version on both.


.. _how_queue_forecasting:

How forecasting jobs are queued
------------------

A forecasting job is an order to create forecasts based on measurements.
A job can be about forecasting one point in time or about forecasting a range of points.

In FlexMeasures, the usual way of creating forecasting jobs would be right in the moment when new power, weather or price data arrives through the API (see :ref:`tut_posting_data`).
So technically, you don't have to do anything to keep fresh forecasts.

The decision which horizons to forecast is currently also taken by FlexMeasures. For power data, FlexMeasures makes this decision depending on the asset resolution. For instance, a resolution of 15 minutes leads to forecast horizons of 1, 6, 24 and 48 hours. For price data, FlexMeasures chooses to forecast prices forward 24 and 48 hours
These are decent defaults, and fixing them has the advantage that schedulers (see below) will know what to expect. However, horizons will probably become more configurable in the near future of FlexMeasures.

You can also add forecasting jobs directly via the CLI. We explain this practice in the next section. 



Historical forecasts
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There might be reasons to add forecasts of past time ranges. For instance, for visualization of past system behavior and to check how well the forecasting models have been doing on a longer stretch of data.

If you host FlexMeasures yourself, we provide a CLI task for adding forecasts for whole historic periods. This is an example call:

Here we request 6-hour forecasts to be made for two sensors, for a period of two days:

.. code-block:: bash

    $ flexmeasures add forecasts --sensor 2 --sensor 3 \
        --from-date 2015-02-01 --to-date 2015-08-31 \
        --horizon 6 --as-job

This is half a year of data, so it will take a while.

It can be good advice to dispatch this work in smaller chunks.
Alternatively, note the ``--as-job`` parameter.
If you use it, the forecasting jobs will be queued and picked up by worker processes (see above). You could run several workers (e.g. one per CPU) to get this work load done faster.

Run ``flexmeasures add forecasts --help`` for more information.


.. _how_queue_scheduling:

How scheduling jobs are queued
------------------

In FlexMeasures, a scheduling job is an order to plan optimised actions for flexible devices.
It usually involves a linear program that combines a state of energy flexibility with forecasted data to draw up a consumption or production plan ahead of time.

There are two ways to queue a scheduling job:

First, we can add a scheduling job to the queue via the API.
We already learned about the `[POST] /schedules/trigger <../api/v3_0.html#post--api-v3_0-sensors-(id)-schedules-trigger>`_ endpoint in :ref:`posting_flex_states`, where we saw how to post a flexibility state (in this case, the state of charge of a battery at a certain point in time).

Here, we extend that (storage) example with an additional target value, representing a desired future state of charge.

.. code-block:: json

    {
        "start": "2015-06-02T10:00:00+00:00",
        "flex-model": {
            "soc-at-start": "12.1 kWh",
            "soc-targets": [
                {
                    "value": "25 kWh",
                    "datetime": "2015-06-02T16:00:00+00:00"
                }
        }
    }


We now have described the state of charge at 10am to be ``"12.1 kWh"``. In addition, we requested that it should be ``"25 kWh"`` at 4pm.
For instance, this could mean that a car should be charged at 90% at that time.

If FlexMeasures receives this message, a scheduling job will be made and put into the queue. In turn, the scheduling job creates a proposed schedule. We'll look a bit deeper into those further down in :ref:`getting_schedules`.

.. note:: Even without a target state of charge, FlexMeasures will create a scheduling job. The flexible device can then be used with more freedom to reach the system objective (e.g. buy power when it is cheap, store it, and sell back when it's expensive).


A second way to add scheduling jobs is via the CLI, so this is available for people who host FlexMeasures themselves:

.. code-block:: bash

    $ flexmeasures add schedule for-storage --sensor 1 --consumption-price-sensor 2 \
        --start 2022-07-05T07:00+01:00 --duration PT12H \
        --soc-at-start 50% --roundtrip-efficiency 90% --as-job

Here, the ``--as-job`` parameter makes the difference for queueing ― without it, the schedule is computed right away.

Run ``flexmeasures add schedule for-storage --help`` for more information.


.. _getting_prognoses:

Getting power forecasts (prognoses)
-----------------

Prognoses (the USEF term used for power forecasts) are used by FlexMeasures to determine the best control signals to valorise on balancing opportunities.

You can access forecasts via the FlexMeasures API at `[GET] /sensors/data <../api/v3_0.html#get--api-v3_0-sensors-data>`_.
Getting them might be useful if you want to use prognoses in your own system, or to check their accuracy against meter data, i.e. the realised power measurements.
The FlexMeasures UI also lists forecast accuracy, and visualises prognoses and meter data next to each other.

A prognosis can be requested at a URL looking like this:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/sensors/data

This example requests a prognosis for 24 hours, with a rolling horizon of 6 hours before realisation.

.. code-block:: json

    {
        "type": "GetPrognosisRequest",
        "sensor": "ea1.2021-01.io.flexmeasures.company:fm1.1",
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT24H",
        "horizon": "PT6H",
        "resolution": "PT15M",
        "unit": "MW"
    }


.. _getting_schedules:

Getting schedules (control signals)
-----------------------

We saw above how FlexMeasures can create optimised schedules with control signals for flexible devices (see :ref:`posting_flex_states`). You can access the schedules via the `[GET] /schedules/<uuid> <../api/v3_0.html#get--api-v3_0-sensors-(id)-schedules-(uuid)>`_ endpoint. The URL then looks like this:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/sensors/<id>/schedules/<uuid>

Here, the schedule's Universally Unique Identifier (UUID) should be filled in that is returned in the `[POST] /schedules/trigger <../api/v3_0.html#post--api-v3_0-sensors-(id)-schedules-trigger>`_ response.
Schedules can be queried by their UUID for up to 1 week after they were triggered (ask your host if you need to keep them around longer).
Afterwards, the exact schedule can still be retrieved through the `[GET] /sensors/data <../api/v3_0.html#get--api-v3_0-sensors-data>`_, using precise filter values for ``start``, ``prior`` and ``source``.

The following example response indicates that FlexMeasures planned ahead 45 minutes for the requested battery power sensor.
The list of consecutive power values represents the target consumption of the battery (negative values for production).
Each value represents the average power over a 15 minute time interval.

.. sourcecode:: json

        {
            "values": [
                2.15,
                3,
                2
            ],
            "start": "2015-06-02T10:00:00+00:00",
            "duration": "PT45M",
            "unit": "MW"
        }

How to interpret these control signals?

One way of reaching the target consumption in this example is to let the battery start to consume with 2.15 MW at 10am,
increase its consumption to 3 MW at 10.15am and decrease its consumption to 2 MW at 10.30am.

However, because the targets values represent averages over 15-minute time intervals, the battery still has some degrees of freedom.
For example, the battery might start to consume with 2.1 MW at 10.00am and increase its consumption to 2.25 at 10.10am,
increase its consumption to 5 MW at 10.15am and decrease its consumption to 2 MW at 10.20am.
That should result in the same average values for each quarter-hour.
