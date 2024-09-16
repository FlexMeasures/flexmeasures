.. _tut_v2g:

A flex-modeling tutorial for storage: Vehicle-to-grid
------------------------------------------------------

The most powerful concept of FlexMeasures is the flex-model. We feel it is time to pay more attention to it and illustrate its effects.

As a demonstration of how to construct a suitable flex model for a given use case, let us for a moment consider a use case where FlexMeasures is asked (through API calls) to compute :abbr:`V2G (vehicle-to-grid)` schedules.
(For a more general introduction to flex modeling, see :ref:`describing_flexibility`.)

In this example, the client is interested in the following:

1. :ref:`battery_protection`: Protect the battery from degradation by constraining any cycling between 25% and 85% of its available storage capacity.
2. :ref:`car_reservations`: Ensure a minimum :abbr:`SoC (state of charge)` of 95% based on a reservation calendar for the car.
3. :ref:`earning_by_cycling`: Use the car battery to earn money (given some dynamic tariff) so long as the above constraints are met.

The following chart visualizes how constraints 1 and 2 can be formulated within a flex model, such that the resulting scheduling problem becomes feasible. A solid line shows a feasible solution, and a dashed line shows an infeasible solution.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/v2g_minima_maxima.png
    :align: center
|


.. _battery_protection:

Battery protection
==================

Let's consider a car battery with a storage capacity of 60 kWh, to be scheduled in 5-minute intervals.
Constraining the cycling to occur within a static 25-85% SoC range can be modelled through the following ``soc-min`` and ``soc-max`` fields of the flex model:

.. code-block:: json

    {
        "flex-model": {
            "soc-min": "15 kWh",
            "soc-max": "51 kWh"
        }
    }

A starting SoC below 15 kWh (25%) will lead to immediate charging to get within limits (as shown above).
Likewise, a starting SoC above 51 kWh (85%) would lead to immediate discharging.
Setting a SoC target outside of the static range leads to an infeasible problem and will be rejected by the FlexMeasures API.

The soc-min and soc-max settings are constant constraints.
To enable a temporary target SoC of more than 85% (for car reservations, see the next section), it is necessary to relax the ``soc-max`` field to 60 kWh (100%), and to instead use the ``soc-maxima`` field to convey the desired upper limit for regular cycling:

.. code-block:: json

    {
        "flex-model": {
            "soc-min": "15 kWh",
            "soc-max": "60 kWh",
            "soc-maxima": [
                {
                    "value": "51 kWh",
                    "start": "2024-02-04T10:35:00+01:00",
                    "end": "2024-02-05T04:25:00+01:00"
                }
            ]
        }
    }

The maxima constraints should be relaxed—or withheld entirely—within some time window before any SoC target (as shown above).
This time window should be at least wide enough to allow the target to be reached in time, and can be made wider to allow the scheduler to take advantage of favourable market prices along the way.


.. _car_reservations:

Car reservations
================

Given a reservation for 8 AM on February 5th, constraint 2 can be modelled through the following (additional) ``soc-minima`` constraint:

.. code-block:: json

    {
        "flex-model": {
            "soc-minima": [
                {
                    "value": "57 kWh",
                    "datetime": "2024-02-05T08:00:00+01:00"
                }
            ]
        }
    }

This constraint also signals that if the car is not plugged out of the Charge Point at 8 AM, the scheduler is in principle allowed to start discharging immediately afterwards.
To make sure the car remains at or above 95% SoC for some time, additional soc-minima constraints should be set accordingly, taking into account the scheduling resolution (here, 5 minutes). For example, to keep it charged (nearly) fully until 8.15 AM:

.. code-block:: json

    {
        "flex-model": {
            "soc-minima": [
                {
                    "value": "57 kWh",
                    "start": "2024-02-05T08:00:00+01:00",
                    "end": "2024-02-05T08:15:00+01:00"
                }
            ]
        }
    }

The car may still charge and discharge within those 15 minutes, but it won't go below 95%.
Alternatively, to keep the car from discharging altogether during that time, limit the ``production-capacity`` (likewise, use the ``consumption-capacity`` to prevent any charging):

.. code-block:: json

    {
        "flex-model": {
            "soc-minima": [
                {
                    "value": "57 kWh",
                    "datetime": "2024-02-05T08:00:00+01:00"
                }
            ],
            "production-capacity": [
                {
                    "value": "0 kW",
                    "start": "2024-02-05T08:00:00+01:00",
                    "end": "2024-02-05T08:15:00+01:00"
                }
            ]
        }
    }

.. _earning_by_cycling:

Earning by cycling
==================

To provide an incentive for cycling the battery in response to market prices, the ``consumption-price`` and ``production-price`` fields of the flex context may be used, which define the sensor IDs under which the price data is stored that is relevant to the given site:

.. code-block:: json

    {
        "flex-context": {
            "consumption-price": {"sensor": 41},
            "production-price": {"sensor": 42}
        }
    }


We hope this demonstration helped to illustrate the flex-model of the storage scheduler. Until now, optimizing storage (like batteries) has been the sole focus of these tutorial series.
In :ref:`tut_toy_schedule_process`, we'll turn to something different: the optimal timing of processes with fixed energy work and duration.