.. _v2g:

Vehicle-to-grid
---------------

As a demonstration of how to construct a suitable flex model for a given use case, we consider a client using FlexMeasures to compute :abbr:`V2G (vehicle-to-grid)` schedules. In this example, the client is interested in the following:

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
            "soc-min": 15,
            "soc-max": 51,
            "soc-unit": "kWh"
        }
    }

A starting SoC below 15 kWh (25%) will lead to immediate charging to get within limits (as shown above).
Likewise, a starting SoC above 51 kWh (85%) would lead to immediate discharging.
Setting a SoC target outside of the static range leads to an infeasible problem and will be rejected by the FlexMeasures API.

To enable a target SoC above 85% (as shown above), it is necessary to set the ``soc-max`` field to 60 kWh (100%), and to instead use the ``soc-maxima`` field to convey the desired upper limit for regular cycling:

.. code-block:: json

    {
        "flex-model": {
            "soc-min": 15,
            "soc-max": 60,
            "soc-maxima": [
                {
                    "value": 51,
                    "datetime": "2024-02-05T12:00:00+01:00"
                },
                {
                    "value": 51,
                    "datetime": "2024-02-05T12:05:00+01:00"
                },
                ...
                {
                    "value": 51,
                    "datetime": "2024-02-05T13:25:00+01:00"
                },
                {
                    "value": 51,
                    "datetime": "2024-02-05T13:30:00+01:00"
                }
            ],
            "soc-unit": "kWh"
        }
    }

The maxima constraints should be relaxed—or withheld entirely—within some time window before any SoC target (as shown above).


.. _car_reservations:

Car reservations
================

Given a reservation for 2 PM on February 5th, constraint 2 can be modelled through the following ``soc-minima`` constraint:

.. code-block:: json

    {
        "flex-model": {
            "soc-minima": [
                {
                    "value": 57,
                    "datetime": "2024-02-05T14:00:00+01:00"
                }
            ]
        }
    }

This constraint also signals that if the car is not plugged out of the Charge Point at 2PM, the scheduler is in principle allowed to start discharging immediately afterwards.
To make sure the car remains at 95% SoC for some time, additional soc-minima constraints should be set accordingly, taking into account the scheduling resolution (here, 5 minutes). For example, to keep it charged (nearly) fully until 2.15 PM:

.. code-block:: json

    {
        "flex-model": {
            "soc-minima": [
                {
                    "value": 57,
                    "datetime": "2024-02-05T14:00:00+01:00"
                },
                {
                    "value": 57,
                    "datetime": "2024-02-05T14:05:00+01:00"
                },
                {
                    "value": 57,
                    "datetime": "2024-02-05T14:10:00+01:00"
                },
                {
                    "value": 57,
                    "datetime": "2024-02-05T14:15:00+01:00"
                }
            ]
        }
    }


.. _earning_by_cycling:

Earning by cycling
==================

To provide an incentive for cycling the battery in response to market prices, the ``consumption-price-sensor`` and ``production-price-sensor`` fields of the flex context may be used, which define the sensor IDs under which the price data is stored that is relevant to the given site:

.. code-block:: json

    {
        "flex-context": {
            "consumption-price-sensor": 41,
            "production-price-sensor": 42
        }
    }
