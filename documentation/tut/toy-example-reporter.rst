.. _tut_toy_schedule_reporter:

Toy example IV: Computing reports
=====================================

.. warning::
    The reporting functionality is still in an early development stage. Beware that major changes might be introduced.
    
So far, we have worked on scheduling batteries and processes. Now, we are moving to one of the other three pillars of FlexMeasures: reporting. 

In essence, reporters apply arbitrary transformations to data coming from some sensors (multiple inputs) and save the results to other sensors (multiple outputs). In practice, this allows to compute KPIs (such as profit and total daily energy production), to apply operations to beliefs (e.g. changing the sign of a power sensor for some time period), among other things.

.. note:: 
    Currently, FlexMeasures comes with the following reporters:
        - `PandasReporter`: applies arbitrary `Pandas <https://pandas.pydata.org>`_ methods to sensor data. 
        - `AggregatorReporter`: combines data from multiple sensors into one using any of the methods supported by the Pandas `aggregate` function (e.g. sum, average, max, min...).
        - `ProfitOrLossReporter`: computes the profit/loss due to an energy flow under a specific tariff.

    Moreover, it's possible to implement your custom reporters in plugins. Instructions for this to come.

Now, coming back to the tutorial, we are going to use the `AggregatorReporter` and the `ProfitOrLossReporter`. In the first part, we'll use the `AggregatorReporter` to compute the (discharge) headroom of the battery in :ref:`tut_toy_schedule_expanded`. That way, we can verify the maximum power at which the battery can discharge at any point of time. In the second part, we'll use the `ProfitOrLossReporter` to compute the costs of operating the process of Tut. Part III in the different policies.

Before getting to the meat of the tutorial, we need to set up up all the entities. Instead of having to do that manually (e.g. using commands such as ``flexmeasures add sensor``), we have prepared a command that does that automatically.

Setup
.....

Just as in previous sections, we need to run the command ``flexmeasures add toy-account``, but this time with a different value for *kind*:

.. code-block:: bash

    $ flexmeasures add toy-account --kind reporter

Under the hood, this command is adding the following entities:
    - A yearly sensor that stores the capacity of the grid connection.
    - A power sensor, `headroom`, to store the remaining capacity for the battery. This is where we'll store the report.
    - A `ProfitOrLossReporter` configured to use the prices that we set up in Tut. Part II.
    - Three sensors to register the profits/losses from running the three different processes of Tut. Part III.

Let's check it out! 

Run the command below to show the values for the `grid connection capacity`:

.. code-block:: bash

    $ TOMORROW=$(date --date="next day" '+%Y-%m-%d')
    $ flexmeasures show beliefs --sensor 7 --start ${TOMORROW}T00:00:00+02:00 --duration PT24H --resolution PT1H
      
      Beliefs for Sensor 'grid connection capacity' (ID 7).
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
                        ██ grid connection capacity


Moreover, we can check the freshly created source `<Source id=6>`, which defines the `ProfitOrLossReporter` with the required configuration.
You'll notice that the `config` is under the `data_generator` field.
That's because reporters belong to a bigger category of classes that also contains the `Schedulers` and `Forecasters`.

.. code-block:: bash

    $ flexmeasures show data-sources --show-attributes --id 6

         ID  Name          Type      User ID    Model           Version    Attributes                                  
       ----  ------------  --------  ---------  --------------  ---------  -----------------------------------------   
          6  FlexMeasures  reporter             ProfitOrLossReporter           {                                            
                                                                               "data_generator": {                      
                                                                                   "config": {                          
                                                                                       "consumption_price_sensor": 1     
                                                                                   }                                     
                                                                               }                                          
                                                                           }                                             


Compute headroom
-------------------

In this case, the discharge headroom is nothing but the difference between the grid connection capacity and the PV power. To compute that quantity, we can use the `AggregatorReporter` using the weights to make the PV to subtract the grid connection capacity.

In practice, we need to create the `config` and `parameters`:

.. code-block:: bash

    $ echo "
    $ {
    $    'weights' : {
    $        'grid connection capacity' : 1.0,
    $        'PV' : -1.0,
    $    }
    $ }" > headroom-config.json


.. code-block:: bash

    $ echo "
    $ {
    $     'input' : [{'name' : 'grid connection capacity','sensor' : 7},
    $                {'name' : 'PV', 'sensor' : 3}],
    $     'output' : [{'sensor' : 8}]
    $ }" > headroom-parameters.json


Finally, we can create the reporter with the following command:

.. code-block:: bash

    $ flexmeasures add report --reporter AggregatorReporter \
       --parameters headroom-parameters.json --config headroom-config.json \
       --start-offset DB,1D --end-offset DB,2D \
       --resolution PT15M

Now we can visualize the headroom in the following `link <http://localhost:5000/sensors/8>`_, which should resemble the following image.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-headroom.png
    :align: center
|

The graph shows that the capacity of the grid is at full disposal for the battery when there's no sun (thus no PV generation), while at noon the battery can only discharge at 280kW max.

Process scheduler profit
-------------------------

For the second part of this tutorial, we are going to use the `ProfitOrLossReporter` to compute the losses (defined as `cost - revenue`) of operating the process from Tut.
Part III, under the three different policies: INFLEXIBLE, BREAKABLE and SHIFTABLE.

In addition, we'll explore another way to invoke reporters: data generators.
Without going too much into detail, data generators create new data.
The thee main types are: `Reporters`, `Schedulers` and `Forecasters`.
This will come handy as the three reports that we are going to create share the same `config`.
The `config` defines the price sensor to use and sets the reporter to work in **losses** mode, which means that it will return costs as positive values and revenue as negative values.

Still, we need to define the parameters.
The three reports share the same structure for the parameters with the following fields:

    - `input`: sensor that stores the power/energy flow. The number of sensors is limited to 1.
    - `output`: sensor to store the report. We can provide sensors with different resolutions to store the same results at different time scales.

.. note::
    It's possible to define the `config` and `parameters` in JSON or YAML formats.

After setting up `config` and `parameters`, we can invoke the reporter using the command ``flexmeasures add report``.
The command takes the data source id, the files containing the parameters and the timing parameters (start and end).
For this particular case, we make use of the offsets to indicate that we want the report to encompass the day of tomorrow.

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


Check the results `here <http://localhost:5000/sensors/9>`_. The image should be similar to the one below.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-inflexible.png
    :align: center
|


Breakable process
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

Check the results `here <http://localhost:5000/sensors/10>`_. The image should be similar to the one below.


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

Check the results `here <http://localhost:5000/sensors/11>`_. The image should be similar to the one below.


.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-shiftable.png
    :align: center
|


Now, we can compare the results of the reports to the ones we computed manually in :ref:`this table <table-process>`). Keep in mind that the
report is showing the profit of each 15min period and adding them all shows that it matches with our previous results.
