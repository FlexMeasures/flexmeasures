.. _tut_toy_schedule_process:

Toy example III: Computing schedules for processes
====================================================

Until this point we've been using a static battery, one of the most flexible energy assets, to reduce electricity bills. A battery can modulate rather freely, and both charge and discharge.


However, in some settings, we can reduce electricity bills by **just** smartly timing the necessary work that we know we have to do. We call this work a "process". In other words, if the process can be displaced, by breaking it into smaller consumption periods or shifting its start time, the process run can match the lower price hours better.

For example, we could have a load that consumes energy at a constant rate (e.g. 200kW) for a fixed duration (e.g. 4h), but there's some flexibility in the start time. In that case, we could find the optimal start time in order to minimize the energy cost.

Examples of flexible processes are: 
    - Water irrigation in agriculture
    - Mechanical pulping in the paper industry
    - Water pumping in waste water management
    - Cooling for the food industry


For consumers under :abbr:`ToU (Time of Use)` tariffs, FlexMeasures `ProcessScheduler` can plan the start time of the process to minimize the overall cost of energy.
Alternatively, it can create a consumption plan to minimize the CO₂ emissions.


In this tutorial, you'll learn how to schedule processes using three different policies: INFLEXIBLE, BREAKABLE and SHIFTABLE. 

Moreover, we'll touch upon the use of time restrictions to avoid scheduling a process in certain times of the day.


Setup
.....


Before moving forward, we'll add the `process` asset and three sensors to store the schedules resulting from following three different policies.

.. code-block:: bash

    $ flexmeasures add toy-account --kind process
    
        Account '<Account Toy Account (ID:1)>' already exists. Skipping account creation. Use `flexmeasures delete account --id 1` if you need to remove it.
        User with email toy-user@flexmeasures.io already exists in account Toy Account.
        The sensor recording day-ahead prices is day-ahead prices (ID: 1).
        Created <GenericAsset None: 'toy-process' (process)>
        Created Power (INFLEXIBLE)
        Created Power (BREAKABLE)
        Created Power (SHIFTABLE)
        The sensor recording the power of the INFLEXIBLE load is Power (INFLEXIBLE) (ID: 4).
        The sensor recording the power of the BREAKABLE load is Power (BREAKABLE) (ID: 5).
        The sensor recording the power of the SHIFTABLE load is Power (SHIFTABLE) (ID: 6).



Trigger an updated schedule
----------------------------

In this example, we are planning to consume at a 200kW constant power for a period of 4h. 

This load is to be schedule for tomorrow, except from the period from 3pm to 4pm (imposed using the ``--forbid`` flag).


Now we are ready to schedule a process. Let's start with the INFLEXIBLE policy, the simplest.

.. code-block:: bash

    flexmeasures add schedule for-process --sensor 4 --consumption-price-sensor 1\
      --start ${TOMORROW}T00:00:00+02:00 --duration PT24H --process-duration PT4H \
      --process-power 0.2MW --process-type INFLEXIBLE \ 
      --forbid "{\"start\" : \"${TOMORROW}T15:00:00+02:00\", \"duration\" : \"PT1H\"}"

Under the INFLEXIBLE policy, the process starts as soon as possible, in this case, coinciding with the start of the planning window.

Following the INFLEXIBLE policy, we'll schedule the same 4h block using a BREAKABLE policy.

.. code-block:: bash

    flexmeasures add schedule for-process --sensor 5 --consumption-price-sensor 1\
      --start ${TOMORROW}T00:00:00+02:00 --duration PT24H --process-duration PT4H \
      --process-power 0.2MW --process-type BREAKABLE \ 
      --forbid "{\"start\" : \"${TOMORROW}T15:00:00+02:00\", \"duration\" : \"PT1H\"}"
 
The BREAKABLE policy splits or breaks the process into blocks that can be scheduled discontinuously. The smallest possible unit is (currently) determined by the sensor's resolution. 

Finally, we'll schedule the process using the SHIFTABLE policy.

.. code-block:: bash

    flexmeasures add schedule for-process --sensor 6 --consumption-price-sensor 1\
      --start ${TOMORROW}T00:00:00+02:00 --duration PT24H --process-duration PT4H \
      --process-power 0.2MW --process-type SHIFTABLE \ 
      --forbid "{\"start\" : \"${TOMORROW}T15:00:00+02:00\", \"duration\" : \"PT1H\"}"
 

Results
---------

The image below shows the resulting schedules following each of the three policies. You will see similar results in your `FlexMeasures UI <http://localhost:5000/assets/5>`_. 

 
.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/asset-view-process.png
    :align: center
|


In the first policy, there's no flexibility and it needs to schedule the process as soon as possible. 
Meanwhile, in the BREAKABLE policy, the consumption blocks surrounds the time restriction to consume in the cheapest hours. Among the three polices, the BREAKABLE policy can achieve the best 
Finally, in the SHIFTABLE policy, the process is shifted to capture the best prices, avoiding the time restrictions.


Let's list the power price the policies achieved for each of the four blocks they scheduled:

.. _table-process:

+-------------------------+------------+-----------+-----------+
|          Block          | INFLEXIBLE | BREAKABLE | SHIFTABLE |
+=========================+============+===========+===========+
|            1            |   10.00    |   5.00    |   10.00   |
+-------------------------+------------+-----------+-----------+
|            2            |   11.00    |   4.00    |   8.00    |
+-------------------------+------------+-----------+-----------+
|            3            |   12.00    |   5.50    |   5.00    |
+-------------------------+------------+-----------+-----------+
|            4            |   15.00    |   7.00    |   4.00    |
+-------------------------+------------+-----------+-----------+
| Average Price (EUR/MWh) |   12.00    |   5.37    |   6.75    |
+-------------------------+------------+-----------+-----------+
|    Total Cost (EUR)     |    9.60    |   4.29    |   5.40    |
+-------------------------+------------+-----------+-----------+

Quantitatively, comparing the total cost of running the process under each policy, the BREAKABLE policy achieves the best results. This is because it can fit much more consumption blocks in the cheapest hours.

This tutorial showed a quick way to optimize the activation of processes. In :ref:`tut_toy_schedule_reporter`, we'll turn away from scheduling, and towards another important FlexMeasures feature: using *reporters* to apply transformations to sensor data.
