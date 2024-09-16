.. _tut_toy_schedule:

Toy example I: Scheduling a battery, from scratch
===============================================

Let's walk through an example from scratch! We'll optimize a 12h-schedule for a battery that is half full.

Okay, let's get started!

.. note:: You can copy the commands by hovering on the top right corner of code examples. You'll copy only the commands, not the output!

.. note:: If you haven't run through :ref:`tut_install_load_data` yet, do that first. There, we added power prices for a 24h window.




Make a schedule
---------------------------------------

After going through the setup, we can finally create the schedule, which is the main benefit of FlexMeasures (smart real-time control).

We'll ask FlexMeasures for a schedule for our (dis)charging sensor (ID 2). We also need to specify what to optimize against. Here we pass the Id of our market price sensor (ID 1).
To keep it short, we'll only ask for a 12-hour window starting at 7am. Finally, the scheduler should know what the state of charge of the battery is when the schedule starts (50%) and what its roundtrip efficiency is (90%).

.. code-block:: bash

    $ flexmeasures add schedule for-storage --sensor 2 --consumption-price-sensor 1 \
        --start ${TOMORROW}T07:00+01:00 --duration PT12H \
        --soc-at-start 50% --roundtrip-efficiency 90%
    New schedule is stored.

Great. Let's see what we made:

.. code-block:: bash

    $ flexmeasures show beliefs --sensor 2 --start ${TOMORROW}T07:00:00+01:00 --duration PT12H
    Beliefs for Sensor 'discharging' (ID 2).
    Data spans 12 hours and starts at 2022-03-04 07:00:00+01:00.
    The time resolution (x-axis) is 15 minutes.
    ┌────────────────────────────────────────────────────────────┐
    │   ▐            ▐▀▀▌                                     ▛▀▀│ 0.5MW
    │   ▞▌           ▌  ▌                                     ▌  │
    │   ▌▌           ▌  ▐                                    ▗▘  │
    │   ▌▌           ▌  ▐                                    ▐   │
    │  ▐ ▐          ▐   ▐                                    ▐   │
    │  ▐ ▐          ▐   ▝▖                                   ▞   │
    │  ▌ ▐          ▐    ▌                                   ▌   │
    │ ▐  ▝▖         ▌    ▌                                   ▌   │
    │▀▘───▀▀▀▀▖─────▌────▀▀▀▀▀▀▀▀▀▌─────▐▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▘───│ 0.0MW
    │         ▌    ▐              ▚     ▌                        │
    │         ▌    ▞              ▐    ▗▘                        │
    │         ▌    ▌              ▐    ▞                         │
    │         ▐   ▐               ▝▖   ▌                         │
    │         ▐   ▐                ▌  ▗▘                         │
    │         ▐   ▌                ▌  ▐                          │
    │         ▝▖  ▌                ▌  ▞                          │
    │          ▙▄▟                 ▐▄▄▌                          │ -0.5MW
    └────────────────────────────────────────────────────────────┘
               10           20           30          40
                            ██ discharging


Here, negative values denote output from the grid, so that's when the battery gets charged.

We can also look at the charging schedule in the `FlexMeasures UI <http://localhost:5000/sensors/2>`_ (reachable via the asset page for the battery):

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-charging.png
    :align: center
|

Recall that we only asked for a 12 hour schedule here. We started our schedule *after* the high price peak (at 4am) and it also had to end *before* the second price peak fully realized (at 8pm). Our scheduler didn't have many opportunities to optimize, but it found some. For instance, it does buy at the lowest price (at 2pm) and sells it off at the highest price within the given 12 hours (at 6pm).

The `asset page for the battery <http://localhost:5000/assets/3>`_ shows both prices and the schedule.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/asset-view-without-solar.png
    :align: center
|

.. note:: The ``flexmeasures add schedule for-storage`` command also accepts state-of-charge targets, so the schedule can be more sophisticated.
   And even more control over schedules is possible through the ``flex-model`` in our API. But that is not the point of this tutorial.
   See ``flexmeasures add schedule for-storage --help`` for available CLI options, :ref:`describing_flexibility` for all flex-model fields or check out the :ref:`tut_v2g` for a tangible example of modelling storage constraints.

This tutorial showed the fastest way to a schedule. In :ref:`tut_toy_schedule_expanded`, we'll go further into settings with more realistic ingredients: solar panels and a limited grid connection.
