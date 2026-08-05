.. _tut_toy_schedule_group_constraints:


Toy example IV: Intermediate power constraints (groups)
================================================================

So far, our flexible devices (the battery and the PV inverter) have only ever been constrained directly by the building's own grid connection capacity.
But in reality, several devices are often physically wired together behind a shared piece of equipment before they reach the site's connection, and that piece of equipment has its own power limit.

The classic example is a **hybrid inverter**: a battery and a PV installation share one inverter, and while each device could individually push a lot of power, the inverter itself caps their *combined* power flow.
This is what the ``group`` field in the storage flex-model is for (see :ref:`storage_device_scheduler` for the general explanation). This tutorial shows a fully DB-driven setup, where the entire flex-model lives on the asset tree, and you trigger a schedule for the site with an empty flex-model.

We'll build the following little asset tree:

.. code-block:: text

    site (building)
      └── inverter (hybrid inverter, hard power-capacity 2.5 kW)
            ├── battery (device, group member)
            └── PV (device, group member)

Setting up the asset tree
---------------------------------------

We create the site, the inverter (the group) and the two devices as assets, with the inverter and devices being children of the site.
Each device also needs output sensors to record its schedule (since these devices won't have a dedicated power sensor of their own — they are "asset-only" flex-model entries), and the inverter needs an output sensor for the group's aggregate schedule.

.. code-block:: bash

    $ flexmeasures add asset --name "toy site" --asset-type-id 5 --account-id 1
    Successfully created asset with ID 10.

    $ flexmeasures add asset --name "hybrid inverter" --asset-type-id 5 --account-id 1 --parent-asset 10
    Successfully created asset with ID 11.

    $ flexmeasures add asset --name "toy battery" --asset-type-id 5 --account-id 1 --parent-asset 10
    Successfully created asset with ID 12.

    $ flexmeasures add asset --name "toy PV" --asset-type-id 5 --account-id 1 --parent-asset 10
    Successfully created asset with ID 13.

    $ flexmeasures add sensor --name "inverter aggregate power" --unit MW --event-resolution PT15M --asset-id 11
    Successfully created sensor with ID 21.

    $ flexmeasures add sensor --name "battery consumption" --unit MW --event-resolution PT15M --asset-id 12
    Successfully created sensor with ID 22.
    $ flexmeasures add sensor --name "battery production" --unit MW --event-resolution PT15M --asset-id 12
    Successfully created sensor with ID 23.

    $ flexmeasures add sensor --name "PV production" --unit MW --event-resolution PT15M --asset-id 13
    Successfully created sensor with ID 24.

.. note:: Asset type IDs and IDs returned above will differ in your own setup — substitute your own.

Storing the flex-models on the assets
---------------------------------------

Rather than sending a flex-model with the trigger request, we store each asset's (partial) flex-model directly on the asset. FlexMeasures walks the asset tree and collects these into one combined flex-model when scheduling the site.

You can set an asset's flex-model with ``PATCH /api/v3_0/assets/<id>``, sending a ``flex_model`` field with the JSON below. (The FlexMeasures UI's flex-model editor on the asset's properties page supports this too, and even suggests the parent asset as a candidate for the ``group`` field.)

The battery is a device with both a consumption and production output sensor (it can charge and discharge), belonging to the inverter's group:

.. code-block:: json

    {
        "flex_model": {
            "power-capacity": "2 kW",
            "consumption-capacity": "2 kW",
            "production-capacity": "2 kW",
            "group": {"asset": 11},
            "consumption": {"sensor": 22},
            "production": {"sensor": 23}
        }
    }

Sent as ``PATCH /api/v3_0/assets/12``.

The PV installation only produces, so it only needs a production output sensor:

.. code-block:: json

    {
        "flex_model": {
            "power-capacity": "2 kW",
            "consumption-capacity": "0 kW",
            "production-capacity": "2 kW",
            "group": {"asset": 11},
            "production": {"sensor": 24}
        }
    }

Sent as ``PATCH /api/v3_0/assets/13``.

Finally, the inverter's own flex-model defines the group's hard power-capacity and where to save the group's aggregate schedule (as it has no power sensor of its own, either):

.. code-block:: json

    {
        "flex_model": {
            "power-capacity": "2.5 kW",
            "consumption": {"sensor": 21}
        }
    }

Sent as ``PATCH /api/v3_0/assets/11``.

Note that neither the battery, the PV installation, nor the inverter reference a ``sensor`` field of their own for scheduling purposes — this is what makes them "asset-only" entries. Instead, results are always saved via their ``consumption``/``production`` output sensor references.

Triggering the schedule
---------------------------------------

We now trigger a schedule for the site (asset 10) with an empty (or omitted) flex-model. Everything the scheduler needs is picked up from the DB-stored flex-models on the asset tree.

.. tabs::

    .. tab:: CLI

        .. code-block:: bash

            $ flexmeasures add schedule \
                --asset 10 \
                --start ${TOMORROW}T00:00+01:00 --duration PT4H \
                --flex-model '[]'
            New schedule is stored.

    .. tab:: API

        Example call: `[POST] http://localhost:5000/api/v3_0/assets/10/schedules/trigger <../api/v3_0.html#post--api-v3_0-assets-id-schedules-trigger>`_ (update the start date to tomorrow):

        .. code-block:: json

            {
                "start": "2026-07-11T00:00+01:00",
                "duration": "PT4H",
                "flex-model": []
            }

Inspecting the results
---------------------------------------

Once the job has finished, three schedules were computed and saved:

- The battery's schedule, split (as it can both charge and discharge) between sensor 22 (``battery consumption``, holding the non-negative, consumption-positive part) and sensor 23 (``battery production``, holding the non-positive part, stored as a positive magnitude).
- The PV installation's schedule, saved entirely to sensor 24 (``PV production``), sign-flipped to be stored as a positive magnitude (since PV only produces).
- The inverter group's aggregate schedule, saved to sensor 21 (``inverter aggregate power``), equal to the (consumption-positive) sum of the battery's and PV's schedules.

You can inspect any of these with:

.. code-block:: bash

    $ flexmeasures show beliefs --sensor 21 --start ${TOMORROW}T00:00:00+01:00 --duration PT4H

The group's aggregate power never exceeds 2.5 kW in either direction — even though the battery and PV could individually reach 2 kW each (4 kW combined) — because the hybrid inverter's hard ``power-capacity`` caps their sum. Without the group, the scheduler could plan the battery to charge at full power during peak PV production, which the inverter physically cannot deliver.

.. note:: If a device only ever consumes or only ever produces, you only need to define the corresponding single output sensor (as we did for the PV installation above). Only devices (or groups) that can go both ways need both a ``consumption`` and a ``production`` output sensor.

This concludes our tour of intermediate power constraints. For the full field reference, see :ref:`storage_device_scheduler` and the "Intermediate power constraints" section of :ref:`scheduling`.
