.. _tut_forecasting_scheduling:

Forecasting & scheduling
========================

Once FlexMeasures has been integrated with data (see :ref:`_tut_posting_data`), you can enjoy its forecasting and scheduling services.
Let's take a look how to set this up (if you are hosting FlexMeasures yourself) and how to access this information.

.. note: If you are not hosting FlexMeasures yourself, skip to :ref:`getting_prognoses`.


Maintaining the queues
------------------------------------

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


Queueing jobs
------------------

TODO: Explain how forecasting jobs are made by the API when new data arrives. Scheduling jobs also, when PostUdiEvent is called. Future work: how can a user configure which assets get this treatment?

TODO: Show that we have flexmeasures add forecasts, example: --from_date 2015-02-02 --to_date 2015-02-04 --horizon_hours 6  --asset-id 2 --as-job
      Drawback: only for complete days (can we change that?)


.. _getting_prognoses:

Getting forecasts (prognoses)
-----------------

Prognoses (the USEF term used for forecasts) are used by FlexMeasures to determine the best control signals to valorise on
balancing opportunities. 

You can access forecasts via the FlexMeasures API at `GET  /api/v2_0/getPrognosis <api/v2_0.html#get--api-v2_0-getPrognosis>`_ 
Getting them might be useful if you want to use prognoses in your own system or to check the accuracy of these forecasts by downloading the prognoses and
comparing them against the meter data, i.e. the realised power measurements (though the FlexMeasures UI also visualises them next to each other).

So a prognosis can be requested for a single asset at the ``getPrognosis`` endpoint, at an URL looking like this:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/getPrognosis

This example requests a prognosis for 24 hours, with a rolling horizon of 6 hours before realisation.

.. code-block:: json

    {
        "type": "GetPrognosisRequest",
        "connection": "ea1.2018-06.io.flexmeasures.company:1:1",
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT24H",
        "horizon": "PT6H",
        "resolution": "PT15M",
        "unit": "MW"
    }


Getting schedules (control signals)
-----------------------

FlexMeasures can create optimised schedules with control signals for flexible devices. You can access the schedules via the `GET  /api/v2_0/getDeviceMessage <api/v2_0.html#get--api-v2_0-getDeviceMessage>`_ endpoint. The URL then looks like this:

.. code-block:: html

    https://company.flexmeasures.io/api/<version>/getDeviceMessage

Control signals can be queried by UDI event for up to 1 week after the UDI event was posted.
This example of a request body shows that we want to look up a control signal for UDI event 203 (which was posted previously, see :ref:`posting_flex_constraints`).

.. code-block:: json

        {
            "type": "GetDeviceMessageRequest",
            "event": "ea1.2018-06.io.flexmeasures.company:7:10:203:soc"
        }

The following example response indicates that FlexMeasures planned ahead 45 minutes for this battery.
The list of consecutive power values represents the target consumption of the battery (negative values for production).
Each value represents the average power over a 15 minute time interval.

.. sourcecode:: json

        {
            "type": "GetDeviceMessageResponse",
            "event": "ea1.2018-06.io.flexmeasures.company:7:10:203",
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
