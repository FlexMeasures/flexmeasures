.. _reporting:

Reporting
============

FlexMeasures feeds upon raw measurement data (e.g. solar generation) and data from third parties (e.g. weather forecasts).

However, there are use cases for enriching these raw data by combining them:

- Pre-calculations: E.g. from a tariff and some tax rules we compute the real financial impact of price data.
- Post-calculations: To be able to show the customer value, we regularly want to compute things like money or CO2 saved.

These calculations can be done with code, but there'll be many repetitions. 

We added an infrastructure that allows us to define computation pipelines and CLI commands for developers to list available reporters and trigger their computations regularly:

- ``flexmeasures show reporters``
- ``flexmeasures add report``

The reporter classes we are designing are using pandas under the hood and can be sub-classed, allowing us to build new reporters from stable simpler ones, and even pipelines. Remember: re-use is developer power!

We believe this infrastructure will become very powerful and enable FlexMeasures hosters and plugin developers to implement exciting new features.

Below are two quick examples, but you can also dive deeper in :ref:`tut_toy_schedule_reporter`.


Example: solar which has not been self-consumed 
------------------------------------------------

So here is a glimpse into a reporter we made - it is based on the ``AggregatorReporter`` (which is for the combination of any two sensors). This simplified example reporter calculates how much of your local PV power has not been covered by your own consumption:

.. code-block:: json

    {
        "beliefs_search_configs": [
            {
                "sensor": 1,
                "source" : 1,
                "alias" : "pv"
            },
            {
                "sensor": 2,
                "source" : 2,
                "alias" : "consumption"
            }
        ],
        "method" : "sum",
        "weights" : {
            "pv" : 1.0,
            "consumption" : -1.0
        }
    }


Example: Profits & losses
---------------------------

A report that should cover a use case right off the shelf for almost everyone using FlexMeasures is the ``ProfitLossReporter`` ― a reporter to compute how profitable your operation has been.
Showing the results of your optimization is a crucial feature, and now easier than ever.

First, reporters can be stored as data sources, so they are easy to be used repeatedly and the data they generate can reference them. Our data source has "ProfitLossReporter" as Model and these attributes (the least a ``ProfitLossReporter`` needs to know is a price): 

.. code-block:: json

    {
      "data_generator": {
        "config": {
          "consumption_price_sensor": 1
        }
      }
    }

And here is excerpts from the tutorial in how to configure and create a report:

.. code-block:: bash
    
    $ echo "
      {
          'input' : [{'sensor' : 4}],
          'output' : [{'sensor' : 9}]
      }" > inflexible-parameters.json

The input sensor stores the power/energy flow, and the output sensor will store the report.

.. code-block:: bash

    $ flexmeasures add report --source 6 \
      --parameters inflexible-parameters.json \
      --start-offset DB,1D --end-offset DB,2D

With these offsets, we indicate that we want the report to encompass the day of tomorrow (see Pandas offset strings).

The report sensor will now store all costs which we know will be made tomorrow by the  schedule.