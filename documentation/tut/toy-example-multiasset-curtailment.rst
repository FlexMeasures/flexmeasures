.. _tut_toy_schedule_multiasset_curtailment:



Toy example III: Multi-asset scheduling, adding PV curtailment
================================================================

TODO: explain

Alternatively, if the solar production is curtailable, we move the solar production to the flex-model.

This makes the PV inverter a flexible control, so this is a good time to move our scheduling command to the building level (asset 2) ― we re officially scheduling the building, not just one device.

There, we tell the scheduler to still work with the battery, but for the PV (represented by sensor 3) to pick any production value between 0 and the production forecast recorded on sensor 3, and to store the resulting schedule on sensor 3 as well (the FlexMeasures UI will still be able to distinguish forecasts from schedules):


Trigger an updated schedule with curtailment
----------------------------------------------------

TODO :Now, we'll reschedule the battery while taking into account the solar production (forecast) as an inflexible device.
This will have an effect on the available headroom for the battery, given the ``site-power-capacity`` limit discussed earlier.

.. tabs::

    .. tab:: CLI

        .. code-block:: bash
            :emphasize-lines: 6

            $ flexmeasures add schedule \
                --asset 2 \
                --start ${TOMORROW}T07:00+01:00 \
                --duration PT12H \
                --soc-at-start 50% \
                --flex-model '[{"sensor": 2, "roundtrip-efficiency": "90%"}, {"sensor": 3, "consumption-capacity": "0 kW", "production-capacity": {"sensor": 3}}]'
            New schedule is stored.

    .. tab:: API

        Example call: `[POST] http://localhost:5000/api/v3_0/sensors/2/schedules/trigger <../api/v3_0.html#post--api-v3_0-sensors-(id)-schedules-trigger>`_ (update the start date to tomorrow):

        .. code-block:: json
            :emphasize-lines: 10-14,16

            {
                "start": "2025-06-11T07:00+01:00",
                "duration": "PT12H",
                "flex-model": [
                    {
                        "sensor": 2,
                        "soc-at-start": "225 kWh",
                        "roundtrip-efficiency": "90%"
                    },
                    {
                        "sensor": 3,
                        "consumption-capacity": "0 kW",
                        "production-capacity": {"sensor": 3},
                    }
                ],
                "flex-context": {}
            }

    .. tab:: FlexMeasures Client

        Using the `FlexMeasures Client <https://pypi.org/project/flexmeasures-client/>`_:

        .. code-block:: bash

            pip install flexmeasures-client

        .. code-block:: python
            :emphasize-lines: 11-15,17

            schedule = await client.trigger_and_get_schedule(
                asset_id=2,  # Toy building (asset ID)
                start=f"{date.today().isoformat()}T07:00+01:00",
                duration="PT12H",
                flex_model=[
                    {
                        "sensor": 2,  # battery power (sensor ID)
                        "soc-at-start": "225 kWh",
                        "roundtrip-efficiency": "90%",
                    },
                    {
                        "sensor": 3,  # solar production (sensor ID)
                        "consumption-capacity": "0 kW",
                        "production-capacity": {"sensor": 3},
                    },
                ],
                flex_context={},  # TODO: add consumption price, as we only have that on the battery so far!! (also API)
            )



We can see the updated scheduling in the `FlexMeasures UI <http://localhost:5000/sensors/2>`_:

TODO
.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-charging-with-solar.png
    :align: center
|

Now our tutorial example has grown quite a bit. This step included scheduling multiple assets (battery and PV inverter), as well as demonstrating a different kind of flexibility: PV curtailment.

In :ref:`tut_v2g`, we will temporarily pause giving you tutorials you can follow step-by-step. We feel it is time to pay more attention to the power of the flex-model, and illustrate its effects.