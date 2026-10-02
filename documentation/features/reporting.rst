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

Reports can be queued for asynchronous processing with ``flexmeasures add report --as-job``.
Run ``flexmeasures jobs run-worker --queue reporting`` to process these jobs. A one-off report
can also be queued through ``POST /api/v3_0/assets/<id>/reports/trigger``. The caller needs read
access to every input and configuration sensor and permission to record data on each output;
outputs are limited to the asset in the URL and its descendants.

The reporter classes we are designing are using pandas under the hood and can be sub-classed, allowing us to build new reporters from stable simpler ones, and even pipelines. Remember: re-use is developer power!

We believe this infrastructure will become very powerful and enable FlexMeasures hosts and plugin developers to implement exciting new features.

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

.. note::
    In addition to filtering by specific data source IDs (``source`` / ``sources``), reporter input data can be filtered using:

    - ``source_types``: list of source type names to include (e.g. ``["forecaster", "scheduler"]``)
    - ``exclude_source_types``: list of source type names to exclude
    - ``account_id``: list of account IDs to include only data from sources belonging to those accounts (note: only matches user-type data sources — DataSources created by reporters, schedulers, and forecasters have no account and will not be matched by this filter)

    These correspond to the same filters available on ``Sensor.search_beliefs``.


Example: the measured aggregate of a device group
---------------------------------------------------

A site that is scheduled has already described its topology in its flex-config:
which devices sit behind which piece of shared equipment (their ``group``), which sensor records each of them,
which sign means consumption or production, and which sensor a group's aggregate belongs on.
The ``AggregatorReporter`` can report the *measured* aggregate of such a group, so the report needs no topology of its own
and cannot drift from the one the scheduler uses.

Take a farm whose PV sits on two installations:

.. code-block:: text

    Farm (site, asset 1)
    └── PV (asset 2)                  sensor 21 "PV production", MW, 15 min   <- the aggregate
        ├── Roof PV (asset 3)         sensor 31 "power", kW, 15 min
        └── Carport PV (asset 4)      sensor 41 "power", MW, 1 hour

The flex-models stored on those assets are all the topology there is:

.. code-block:: json

    {"inflexible-production" : {"sensor" : 31}, "group" : {"asset" : 2}}

.. code-block:: json

    {"inflexible-production" : {"sensor" : 41}, "group" : {"asset" : 2}}

.. code-block:: json

    {"production" : {"sensor" : 21}}

The report's configuration then names only the group:

.. code-block:: json

    {
        "group" : {"asset" : 2}
    }

And its parameters only the period, with a belief horizon of zero to ask for realized values rather than forecasts:

.. code-block:: json

    {
        "start" : "2026-06-01T00:00:00+02:00",
        "end" : "2026-06-02T00:00:00+02:00",
        "belief_horizon" : "PT0H"
    }

With the roof measuring 400 kW and the carport 0.15 MW, sensor 21 receives 0.55 MW for every quarter-hour:
the roof's kilowatts are converted to megawatts, and the carport's hourly values are carried across each quarter of their hour.
Adding a third installation means adding one flex-model entry with ``"group": {"asset": 2}``;
the scheduler and this report both pick it up, with nothing to keep in sync.

**Narrowing a group.** A group is a piece of equipment, so it holds everything behind it.
To report a category instead, filter its members:

.. code-block:: json

    {
        "group" : {"asset" : 1},
        "members" : {"asset-type" : "solar"}
    }

The asset type says what a device *is*, which does not change when the way it is modelled changes,
so a PV installation that later becomes curtailable stays in the aggregate.

**Units and resolutions.** Values are converted to the unit of the output sensor at each sensor's *own* resolution,
before being resampled to the output's resolution.
That order matters for a conversion between a stock and a flow: a sensor recording 1 kWh every quarter of an hour is recording 4 kW,
and treating its data as though it were hourly would report a quarter of the real power.
Resampling then follows the quantity: an energy adds up over a longer event where a power averages over it,
and a power recorded hourly holds through its hour when the output is finer.
A sensor whose quantity the output sensor cannot express, such as a temperature onto a power sensor, is reported as an error
rather than being added up.


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

.. _automating_reports:

Automating reports
--------------------

Instead of computing reports one at a time, you can set up an *automation*: a recurring task defined on an asset, which queues reporting jobs on a cron schedule.
See :ref:`automations`.
