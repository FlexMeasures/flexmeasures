.. _tut_toy_schedule_expanded:



Toy example II: Adding solar production and limited grid connection
====================================================================


So far we haven't taken into account any other devices that consume or produce electricity. The battery was free to use all available capacity towards the grid. 

What if other devices will be using some of that capacity? Our schedules need to reflect that, so we stay within given limits.

.. note:: The capacity is given by ``capacity_in_mw``, an attribute we placed on the battery asset earlier (see :ref:`tut_toy_schedule`). We will tell FlexMeasures to take the solar production into account (using ``--inflexible-device-sensor``) for this capacity limit.

We'll now add solar production forecast data and then ask for a new schedule, to see the effect of solar on the available headroom for the battery.


Adding PV production forecasts
------------------------------

First, we'll create a new CSV file with solar forecasts (MW, see the setup for sensor 3 in part I of this tutorial) for tomorrow.

.. code-block:: bash

    $ TOMORROW=$(date --date="next day" '+%Y-%m-%d')
    $ echo "Hour,Price
    $ ${TOMORROW}T00:00:00,0.0
    $ ${TOMORROW}T01:00:00,0.0
    $ ${TOMORROW}T02:00:00,0.0
    $ ${TOMORROW}T03:00:00,0.0
    $ ${TOMORROW}T04:00:00,0.01
    $ ${TOMORROW}T05:00:00,0.03
    $ ${TOMORROW}T06:00:00,0.06
    $ ${TOMORROW}T07:00:00,0.1
    $ ${TOMORROW}T08:00:00,0.14
    $ ${TOMORROW}T09:00:00,0.17
    $ ${TOMORROW}T10:00:00,0.19
    $ ${TOMORROW}T11:00:00,0.21
    $ ${TOMORROW}T12:00:00,0.22
    $ ${TOMORROW}T13:00:00,0.21
    $ ${TOMORROW}T14:00:00,0.19
    $ ${TOMORROW}T15:00:00,0.17
    $ ${TOMORROW}T16:00:00,0.14
    $ ${TOMORROW}T17:00:00,0.1
    $ ${TOMORROW}T18:00:00,0.06
    $ ${TOMORROW}T19:00:00,0.03
    $ ${TOMORROW}T20:00:00,0.01
    $ ${TOMORROW}T21:00:00,0.0
    $ ${TOMORROW}T22:00:00,0.0
    $ ${TOMORROW}T23:00:00,0.0" > solar-tomorrow.csv

Then, we read in the created CSV file as beliefs data.
This time, different to above, we want to use a new data source (not the user) ― it represents whoever is making these solar production forecasts.
We create that data source first, so we can tell `flexmeasures add beliefs` to use it.
Setting the data source type to "forecaster" helps FlexMeasures to visually distinguish its data from e.g. schedules and measurements.

.. note:: The ``flexmeasures add source`` command also allows to set a model and version, so sources can be distinguished in more detail. But that is not the point of this tutorial. See ``flexmeasures add source --help``.

.. code-block:: bash

    $ flexmeasures add source --name "toy-forecaster" --type forecaster
    Added source <Data source 4 (toy-forecaster)>
    $ flexmeasures add beliefs --sensor 3 --source 4 solar-tomorrow.csv --timezone Europe/Amsterdam
    Successfully created beliefs

The one-hour CSV data is automatically resampled to the 15-minute resolution of the sensor that is recording solar production. We can see solar production in the `FlexMeasures UI <http://localhost:5000/sensors/3>`_ :

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-production.png
    :align: center
|

.. note:: The ``flexmeasures add beliefs`` command has many options to make sure the read-in data is correctly interpreted (unit, timezone, delimiter, etc). But that is not the point of this tutorial. See ``flexmeasures add beliefs --help``.


Trigger an updated schedule
----------------------------

Now, we'll reschedule the battery while taking into account the solar production. This will have an effect on the available headroom for the battery, given the ``capacity_in_mw`` limit discussed earlier.

.. code-block:: bash

    $ flexmeasures add schedule for-storage --sensor 2 --consumption-price-sensor 1 \
        --inflexible-device-sensor 3 \
        --start ${TOMORROW}T07:00+02:00 --duration PT12H \
        --soc-at-start 50% --roundtrip-efficiency 90%
    New schedule is stored.

We can see the updated scheduling in the `FlexMeasures UI <http://localhost:5000/sensors/2>`_ :

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-charging-with-solar.png
    :align: center
|

The `asset page for the battery <http://localhost:5000/assets/3>`_ now shows the solar data, too:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/asset-view-with-solar.png
    :align: center


Though this schedule is quite similar, we can see that it has changed from `the one we computed earlier <https://raw.githubusercontent.com/FlexMeasures/screenshots/main/tut/toy-schedule/asset-view-without-solar.png>`_ (when we did not take solar into account).

First, during the sunny hours of the day, when solar power is being send to the grid, the battery's output (at around 9am and 11am) is now lower, as the battery shares ``capacity_in_mw`` with the solar production. In the evening (around 7pm), when solar power is basically not present anymore, battery discharging to the grid is still at its previous levels.

Second, charging of the battery is also changed a bit (around 10am), as less can be discharged later.

Moreover, we can use reporters to compute the capacity headroom (see :ref:`tut_toy_schedule_reporter` for more details). The image below shows that the scheduler is respecting the capacity limits.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-headroom-pv.png
    :align: center
|

In the case of the scheduler that we ran in the previous tutorial, which did not yet consider the PV, the discharge power would have exceeded the headroom:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-headroom-nopv.png
    :align: center
|

.. note:: You can add arbitrary sensors to a chart using the attribute ``sensors_to_show``. See :ref:`view_asset-data` for more.

A nice feature is that you can check the data connectivity status of your building asset. Now that we have made the schedule, both lamps are green. You can also view it in `FlexMeasures UI <http://localhost:5000/assets/2/status>`_ :

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/screenshot_building_status.png
    :align: center
|

We hope this part of the tutorial shows how to incorporate a limited grid connection rather easily with FlexMeasures. There are more ways to model such settings, but this is a straightforward one.

This tutorial showed a quick way to add an inflexible load (like solar power) and a grid connection.
In :ref:`tut_v2g`, we will temporarily pause giving you tutorials you can follow step-by-step. We feel it is time to pay more attention to the power of the flex-model, and illustrate its effects.
