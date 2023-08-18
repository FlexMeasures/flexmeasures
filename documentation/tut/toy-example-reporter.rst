.. _tut_toy_schedule_reporter:

Toy example IV: Computing reports
=====================================

So far, we have work on the scheduling batteries and processes. Now, we are moving to one of the other the three pillars of FlexMeasures: Reporting. 

In essence, reporters apply arbitrary transformations to data coming from some sensors (multiple inputs) and save the results to other sensors (multiple outputs). In practice, this allows to compute KPIs (e.g. profit, total daily energy production, ...), apply operations to beliefs (e.g. change sign of a power sensor for a time period), among other things. 

Currently, FlexMeasures comes with the following reporters:
    - `PandasReporter`: applies arbitrary pandas methods to sensor data. 
    - `AggregatorReporter`: combines data from multiple sensors into one using any of the Pandas `aggregate` function supported method (e.g. sum, average, max, min...).
    - `ProfitReporter`: computes the cost/profit due to an energy flow under a specific tariff.

Moreover, it's possible to implement your custom reporters in plugins. Instructions for this to come.

Now, coming back to the tutorial, we are going to use the `AggregatorReporter` and the `ProfitReporter`. In the first part, we'll use the `AggregatorReporter` to compute the (discharge) headroom of the battery in :ref:`tut_toy_schedule_expanded`. That way, we can verify the maximum power at which the battery can discharge at any point of time. In the second part, we'll use the `ProfitReporter` to compute the profit of operating the process of Tut. Part III in the different policies.

Before getting to the meat of the tutorial, we need to setup up all the entities. Instead of having to do that manually (e.g. using commands such as ``flexmeasures add sensor```), we have prepared a command that does that automatically.

Setup
.....

Just as in previous sections, we need to run the command ```flexmeasures add toy-account``, but this time with a different value for *kind*:

.. code-block:: bash

    $ flexmeasures add toy-account --kind reporting

Under the hood, this command is adding the following entities:
    - A yearly sensor that stores the capacity of the grid connection.
    - A power sensor, `Headroom`, to store the remaining capacity for the battery. This is where we'll store the report.
    - A `ProfitReporter` configured to use the prices that we setup in Tut. Part II.
    - Three sensors to register the profit of running the process of Tut. Part III.

Let's check it out! 

Run the command below to show the values for the `Grid Connection Capacity`:

.. code-block:: bash

    $ TOMORROW=$(date --date="next day" '+%Y-%m-%d')
    $ flexmeasures show beliefs --sensor-id 7 --start ${TOMORROW}T00:00:00+02:00 --duration PT24H --resolution PT1H
      
      Beliefs for Sensor 'Grid Connection Capacity' (ID 7).
        Data spans a day and starts at 2023-08-14 00:00:00+02:00.
        The time resolution (x-axis) is an hour.
        ┌────────────────────────────────────────────────────────────┐
        │                                                            │ 
        │                                                            │ 
        │                                                            │ 
        │                                                            │ 
        │                                                            │ 1.0MW
        │                                                            │ 
        │                                                            │ 
        │                                                            │ 
        │▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀│ 0.5MW
        │                                                            │ 
        │                                                            │ 
        │                                                            │ 
        │▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁│ 0.0MW
        │                                                            │ 
        │                                                            │ 
        │                                                            │ 
        │                                                            │ -0.5MW
        └────────────────────────────────────────────────────────────┘
                5            10            15           20
                        ██ Grid Connection Capacity


Moreover, we can check the freshly created source `<Source id=6>` which defines the `ProfitReporter` with the required configuration. You'll notice that the `config` is under `data_generator` field. That's because reporter belong to a bigger category of class which also contains the `Schedulers` and `Forecasters`.

.. code-block:: bash

    $ flexmeasures show data-sources --show-attributes --id 6

         ID  Name          Type      User ID    Model           Version    Attributes                                  
       ----  ------------  --------  ---------  --------------  ---------  -----------------------------------------   
          6  FlexMeasures  reporter             ProfitReporter             {                                            
                                                                               "data_generator": {                      
                                                                                   "config": {                          
                                                                                       "consumption_price_sensor": 1     
                                                                                   }                                     
                                                                               }                                          
                                                                           }                                             


Compute headroom
-------------------

In this case, the discharge headroom is nothing but the difference between the *Grid Connection Capacity* and the PV power. To compute that quantity, we can use the `AggregatorReporter` using the weights to make the PV to substract the grid connection capacity.

In practice, we need to create the `config` and `parameters`:

.. code-block:: bash

    $ echo "
    $ {
    $    'weights' : {
    $        'Grid Connection Capacity' : 1.0,
    $        'PV' : -1.0,
    $    }
    $ }" > headroom-config.json


.. code-block:: bash

    $ echo "
    $ {
    $     'input' : [{'name' : 'Grid Connection Capacity','sensor' : 7},
    $                {'name' : 'PV', 'sensor' : 3}],
    $     'output' : [{'sensor' : 8}]
    $ }" > headroom-parameters.json


Finally, we can create the reporter with the following command:

.. code-block:: bash

    $ TOMORROW=$(date --date="next day" '+%Y-%m-%d')
    $ flexmeasures add report --reporter AggregatorReporter \
       --parameters headroom-parameters.json --config headroom-config.json \
       --start-offset DB,1D --end-offset DB,2D \
       --resolution PT15M

Now we can visualize the headroom in the following `link <http://localhost:5000/sensor/8/>`_, it should resemble the following image.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-headroom.png
    :align: center
|

The graph shows that the capacity of the grid is at full disposal for the battery when there's no sun (thus no PV generation), while
at noon the battery can only discharge at 280kW max.

Process scheduler profit
-------------------------

For the second part of this tutorial, we are going to use the `ProfitReporter` to compute the profit (defined as `revenue - cost`) of operating the 
process from Tut. Part III, under the three different policies: INFLEXIBLE, BREAKABLE and SHIFTABLE.

In addition, we'll explore another way to invoke reporters: data generators. Without going too much into detail, data generators
create new data. The thee main types are: `Reporters`, `Schedulers` and `Forecasters`. This will come handy as the three reports that
we are going to create share the same `config`. Still, we need to define the parameters.


Inflexible process
^^^^^^^^^^^^^^^^^^^
Define parameters in a JSON file:

.. code-block:: bash

    $ echo "
    $ {
    $     'input' : [{'sensor' : 4}],
    $     'output' : [{'sensor' : 9}]
    $ }" > inflexible-parameters.json

Create report:

.. code-block:: bash

    $ flexmeasures add report --source 6 \
       --parameters inflexible-parameters.json \
       --start-offset DB,1D --end-offset DB,2D


Check the results `here <http://localhost:5000/sensor/9/>`_. The image should be similar to the one below.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-inflexible.png
    :align: center
|


breakable-parameters process
^^^^^^^^^^^^^^^^^^^
Define parameters in a JSON file:

.. code-block:: bash

    $ echo "
    $ {
    $     'input' : [{'sensor' : 5}],
    $     'output' : [{'sensor' : 10}]
    $ }" > breakable-parameters.json

Create report:

.. code-block:: bash

    $ flexmeasures add report --source 6 \
       --parameters breakable-parameters.json \
       --start-offset DB,1D --end-offset DB,2D

Check the results `here <http://localhost:5000/sensor/10/>`_. The image should be similar to the one below.


.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-breakable.png
    :align: center
|

Shiftable process
^^^^^^^^^^^^^^^^^^^

Define parameters in a JSON file:

.. code-block:: bash

    $ echo "
    $ {
    $     'input' : [{'sensor' : 6}],
    $     'output' : [{'sensor' : 11}]
    $ }" > shiftable-parameters.json

Create report:

.. code-block:: bash

    $ flexmeasures add report --source 6 \
       --parameters shiftable-parameters.json \
       --start-offset DB,1D --end-offset DB,2D

Check the results `here <http://localhost:5000/sensor/11/>`_. The image should be similar to the one below.


.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-shiftable.png
    :align: center
|

Now, we can compare the results of the reports to the ones we computed manually in :ref:`this table <table-process>`). Keep in mind that the
report is showing the profit of each 15min period and adding them all show that it matches with our previous results.
