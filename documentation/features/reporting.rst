.. _reporting:

Reporting
============

FlexMeasures feeds upon raw measurement data (e.g. solar generation) and data from third parties (e.g. weather forecasts).

However, there are use cases for enriching these raw data by combining them:

- Pre-calculations: For example, from a tariff and some tax rules we compute the real financial impact of price data.
- Post-calculations: To be able to show the customer value, we regularly want to compute things like money or CO₂ saved.

These calculations can be done with code, but there'll be many repetitions. 

We added an infrastructure that allows us to define computation pipelines and CLI commands for developers to list available reporters and trigger their computations regularly:

- ``flexmeasures show reporters``
- ``flexmeasures add report``

The reporter classes we are designing are using pandas under the hood and can be sub-classed, allowing us to build new reporters from stable simpler ones, and even pipelines. Remember: re-use is developer power!

We believe this infrastructure will become very powerful and enable FlexMeasures hosters and plugin developers to implement exciting new features.

Below are two quick examples, but you can also dive deeper in :ref:`tut_toy_schedule_reporter`.


Example: solar feed-in / self-consumption delta 
------------------------------------------------

So here is a glimpse into a reporter we made - it is based on the ``AggregatorReporter`` (which is for the combination of any two sensors).
This simplified example reporter basically calculates ``pv - consumption`` at grid connection point.
This tells us how much solar power we fed back to the grid (positive values) and/or the amount of grid power within the overall consumption that did not come from local solar panels (negative values).

This is the configuration of how the computation works:

.. code-block:: json
    
    {
        "method" : "sum",
        "weights" : {
            "pv" : 1.0,
            "consumption" : -1.0
        }
    }

This parameterizes the computation (from which sensors does data come from, which range & where does it go):

.. code-block:: json
    
    {
        "input": [
            {
                "name" : "pv",
                "sensor": 1,
                "source" : 1,
            },
            {
                "name" : "consumption",
                "sensor": 1,
                "source" : 2,
            }
        ],
        "output": [
            {
                "sensor": 3,
            }
        ],
        "start" : "2023-01-01T00:00:00+00:00",
        "end" : "2023-01-03T00:00:00+00:00",
    }



Example: Profits & losses
---------------------------

A report that should cover a use case right off the shelf for almost everyone using FlexMeasures is the ``ProfitOrLossReporter`` ― a reporter to compute how profitable your operation has been.
Showing the results of your optimization is a crucial feature, and now easier than ever.

First, reporters can be stored as data sources, so they are easy to be used repeatedly and the data they generate can reference them.
Our data source has ``ProfitOrLossReporter`` as model attribute and these configuration information stored on its ``attribute`` defines the reporter further (the least a ``ProfitOrLossReporter`` needs to know is a price): 

.. code-block:: json

    {
      "data_generator": {
        "config": {
          "consumption_price_sensor": 1
        }
      }
    }

And here are more excerpts from the tutorial mentioned above.
Here we configure the input and output:

.. code-block:: bash
    
    $ echo "
      {
          'input' : [{'sensor' : 4}],
          'output' : [{'sensor' : 9}]
      }" > profitorloss-parameters.json

The input sensor stores the power/energy flow, and the output sensor will store the report. Recall that we already provided the price sensor to use in the reporter's data source.
 

.. code-block:: bash

    $ flexmeasures add report\
      --source 6 \
      --parameters profitorloss-parameters.json \
      --start-offset DB,1D --end-offset DB,2D

Here, the ``ProfitOrLossReporter`` used as source (with Id 6) is the one we configured above.
With the offsets, we control the timing ― we indicate that we want the new report to encompass the day of tomorrow (see Pandas offset strings).

The report sensor will now store all costs which we know will be made tomorrow by the  schedule.