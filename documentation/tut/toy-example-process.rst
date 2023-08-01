.. _tut_toy_schedule_process:



Toy example III: Computing schedules for processes
====================================================================

Until this point we've been using a static battery, one of the most flexible energy assets, to reduce electricity bills. 

However, in some settings, we can reduce electricity bills by *just* consuming energy smartly. In other words, if the process can be displaced, by breaking it into smaller consumption periods or shifting its start time, the process run can match the lower price hours better.

For example, we could have a load that consumes energy at a constant rate (e.g. 100kW) for a fixed duration (e.g. 3h), but there's some flexibility in the start time. In that case, we could find the optimal start time in order to minimize the energy cost.

Examples of flexible processes are: 
    - Water irrigation in agriculture
    - Mechanical pulping in the paper industry
    - Water pumping in waste water management
    - Cooling for the food industry


For consumers under :abbr:`ToU (Time of Use)` tariffs, FlexMeasures `ProcessScheduler` can plan the start time of the process to minimize the overall cost of energy.
Alternatively, it can create a consumption plan to minimize the CO2 emissions. 


In this tutorial, you'll learn how to schedule processes using three different policies: INFLEXIBLE, BREAKABLE and SHIFTABLE. 

Moreover, we'll touch upon the use of time restrictions to avoid scheduling a process in certain times of the day.


Setup
.....


Before moving forward, we'll add the `process` asset and three sensors to store the schedules resulting from following three different policies.

.. code-block:: bash

    $ flexmeasures add toy-account --kind process

        Asset type solar already exists.
        Asset type wind already exists.
        Asset type one-way_evse already exists.
        Asset type two-way_evse already exists.
        Asset type battery already exists.
        Asset type building already exists.
        Asset type process already exists.
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

In this example, we are planning to consume 200kW for a period of 4h, tomorrow. 

In addition, we'll add a time period in which the scheduler won't be able to run the process.

Now we are ready to schedule a process. Let's start with the INFLEXIBLE policy, the simplest. The scheduler
cannot schedule the process to run within the first hour after midnight.

.. code-block:: bash

    flexmeasures add schedule for-process --sensor-id 4 --consumption-price-sensor 1\
      --start ${TOMORROW}T00:00:00+02:00 --duration PT24H --process-duration PT4H \
      --process-power 0.2MW --process-type INFLEXIBLE \ 
      --forbid "{\"start\" : \"${TOMORROW}T00:00:00+02:00\", \"duration\" : \"PT1H\"}"

This policy consist of scheduling the process as soon as possible. That is from 1am to 5am, as the time restriction from 12am to 1am makes the scheduler unable to start at 12am.

Following the INFLEXIBLE policy, we'll schedule the same 4h block using a BREAKABLE policy.

In this other case, will restrict the period from 2pm to 3pm from scheduling any process. This block corresponds to the lowest price of the day.

.. code-block:: bash

    flexmeasures add schedule for-process --sensor-id 5 --consumption-price-sensor 1\
      --start ${TOMORROW}T00:00:00+02:00 --duration PT24H --process-duration PT4H \
      --process-power 0.2MW --process-type BREAKABLE \ 
      --forbid "{\"start\" : \"${TOMORROW}T14:00:00+02:00\", \"duration\" : \"PT1H\"}"
 
The BREAKABLE policy splits or breaks the process into blocks that can be scheduled discontinuously. 

Finally, we'll schedule the process using the SHIFTABLE policy. We'll keep the same time restrictions as in the BREAKABLE process.



.. code-block:: bash

    flexmeasures add schedule for-process --sensor-id 6 --consumption-price-sensor 1\
      --start ${TOMORROW}T00:00:00+02:00 --duration PT24H --process-duration PT4H \
      --process-power 0.2MW --process-type SHIFTABLE \ 
      --forbid "{\"start\" : \"${TOMORROW}T14:00:00+02:00\", \"duration\" : \"PT1H\"}"
 
 
.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/asset-view-process.png
    :align: center
|

The image above show the schedules following the three policies. 

In the first policy, there's no flexibility and it needs to schedule as soon as possible. Meanwhile, in the BREAKABLE policy, the consumption blocks surrounds the time restriction to consume in the cheapest hours. Finally, in the SHIFTABLE policy, the process is shifted to capture the best prices, avoiding the time restrictions.