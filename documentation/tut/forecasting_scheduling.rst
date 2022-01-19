.. _tut_forecasting_scheduling:

Forecasting & scheduling
========================

Once FlexMeasures contains data (see :ref:`tut_posting_data`), you can enjoy its forecasting and scheduling services.
Let's take a look at how FlexMeasures users can access information from these services, and how you (if you are hosting FlexMeasures yourself) can set up the data science queues for this.

.. contents:: Table of contents
    :local:
    :depth: 1

If you want to learn more about the actual algorithms used in the background, head over to :ref:`algorithms`.


Maintaining the queues
------------------------------------

.. note:: If you are not hosting FlexMeasures yourself, skip right ahead to :ref:`how_queue_forecasting` or :ref:`getting_prognoses`.

Here we assume you have access to a Redis server and configured it (see :ref:`redis-config`).

Start to run one worker for each kind of job (in a separate terminal):

.. code-block::

   flexmeasures run-worker --queue forecasting
   flexmeasures run-worker --queue scheduling


You can also clear the job queues:

.. code-block::

   flexmeasures clear-queue --queue forecasting
   flexmeasures clear-queue --queue scheduling


When the main FlexMeasures process runs (e.g. by ``flexmeasures run``\ ), the queues of forecasting and scheduling jobs can be visited at ``http://localhost:5000/tasks/forecasting`` and ``http://localhost:5000/tasks/schedules``\ , respectively (by admins).

When forecasts and schedules have been generated, they should be visible at ``http://localhost:5000/analytics``.


.. _how_queue_forecasting:

How forecasting jobs are queued
------------------

A forecasting job is an order to create forecasts based on measurements.
A job can be about forecasting one point in time or about forecasting a range of points.


In FlexMeasures, forecasting jobs are created by the server when new power, weather or price data arrives through the API (see :ref:`tut_posting_data`).
So technically, you don't have to do anything to keep fresh forecasts.

The decision which horizons to forecast is currently also taken by FlexMeasures. For power data, FlexMeasures makes this decision depending on the asset resolution. For instance, a resolution of 15 minutes leads to forecast horizons of 1, 6, 24 and 48 hours. For price data, FlexMeasures chooses to forecast prices forward 24 and 48 hours
These are decent defaults, and fixing them has the advantage that scheduling scripts (see below) will know what to expect. However, horizons will probably become more configurable in the near future of FlexMeasures. 

Historical forecasts
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There might be reasons to add forecasts of past time ranges. For instance, for visualisation of past system behaviour and to check how well the forecasting models have been doing on a longer stretch of data.

If you host FlexMeasures yourself, we provide a CLI task for adding forecasts for whole historic periods. This is an example call:

.. code-block:: bash

     flexmeasures add forecasts --from_date 2020-01-02 --to_date 2020-6-30 --horizon_hours 6  --resolution 60 --asset-id 2

Here, forecasts are being computed for asset 2, with one horizon (6 hours) and a resolution of 60 minutes.
This is half a year of data, so it will take a while.
You can also queue this work to workers (see above) with the additional ``--as-job`` parameter (though in general we'd advise to dispatch this work in smaller chunks).

.. _how_queue_scheduling:

How scheduling jobs are queued
------------------

In FlexMeasures, a scheduling job is an order to plan optimised actions for flexible devices.
It usually involves a linear program that combines a state of energy flexibility with forecasted data to draw up a consumption or production plan ahead of time.

We already learned about the ``postUdiEvent`` endpoint in :ref:`posting_flex_states`, where we saw how to post a state of flexibility (in this case, the state of charge of a battery at a certain point in time).

This endpoint can also be used to request a future state of charge (using ``soc-with-target`` in the entity address).

As an example, consider the same UDI event as we saw earlier (in :ref:`posting_flex_states`), but with an additional target value.

.. code-block:: json

    {
        "type": "PostUdiEventRequest",
        "event": "ea1.2021-01.io.flexmeasures.company:7:10:204:soc-with-targets",
        "value": 12.1,
        "datetime": "2015-06-02T10:00:00+00:00",
        "unit": "kWh",
        "targets": [
            {
                "value": 25,
                "datetime": "2015-06-02T16:00:00+00:00"
            }
        ]
    }

Here we have described the state of charge at 10am to be ``12.1``. In addition, we requested that it should be ``25`` at 4pm.
For instance, this could mean that a car should be charged at 90% at that time.

Now here is a task that requires some scheduling. If FlexMeasures receives this UDI Event, a scheduling job will be made and put into the queue. In turn, the forecasting job creates a proposed schedule. We'll look a bit deeper into those further down in :ref:`getting_schedules`;

.. note:: Even without a target state of charge, FlexMeasures will create a scheduling job. The flexible device can then be used with more freedom to reach the system objective (e.g. buy power when it is cheap, store it, and sell back when it's expensive).


.. _getting_prognoses:

Getting power forecasts (prognoses)
-----------------

Prognoses (the USEF term used for power forecasts) are used by FlexMeasures to determine the best control signals to valorise on balancing opportunities.

You can access forecasts via the FlexMeasures API at `GET  /api/v2_0/getPrognosis <../api/v2_0.html#get--api-v2_0-getPrognosis>`_. 
Getting them might be useful if you want to use prognoses in your own system, or to check their accuracy against meter data, i.e. the realised power measurements.
The FlexMeasures UI also lists forecast accuracy, and visualises prognoses and meter data next to each other.

A prognosis can be requested for a single asset at the ``getPrognosis`` endpoint, at a URL looking like this:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/getPrognosis

This example requests a prognosis for 24 hours, with a rolling horizon of 6 hours before realisation.

.. code-block:: json

    {
        "type": "GetPrognosisRequest",
        "connection": "ea1.2021-01.io.flexmeasures.company:fm1.1",
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT24H",
        "horizon": "PT6H",
        "resolution": "PT15M",
        "unit": "MW"
    }


.. _getting_schedules:

Getting schedules (control signals)
-----------------------

We saw above how FlexMeasures can create optimised schedules with control signals for flexible devices. You can access the schedules via the `GET  /api/v2_0/getDeviceMessage <../api/v2_0.html#get--api-v2_0-getDeviceMessage>`_ endpoint. The URL then looks like this:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/getDeviceMessage

Control signals can be queried by UDI event for up to 1 week after the UDI event was posted (ask your host if you need to keep them around longer).
This example of a request body shows that we want to look up a control signal for UDI event 203 (which was posted previously, see :ref:`posting_flex_states`).

.. code-block:: json

        {
            "type": "GetDeviceMessageRequest",
            "event": "ea1.2021-01.io.flexmeasures.company:7:10:203:soc"
        }

The following example response indicates that FlexMeasures planned ahead 45 minutes for this battery.
The list of consecutive power values represents the target consumption of the battery (negative values for production).
Each value represents the average power over a 15 minute time interval.

.. sourcecode:: json

        {
            "type": "GetDeviceMessageResponse",
            "event": "ea1.2021-01.io.flexmeasures.company:7:10:203",
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
