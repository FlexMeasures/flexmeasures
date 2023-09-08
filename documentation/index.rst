Welcome to the FlexMeasures documentation!
===================================================================

When we use a lot of renewable energy, flexibility is becoming crucial and valuable, e.g. for demand response.
FlexMeasures is the intelligent & developer-friendly EMS to support real-time energy flexibility apps, rapidly and scalable.

The problem it helps to solve is:

*What are the best times to run flexible assets, like batteries or heat pumps?*

In a nutshell, FlexMeasures turns data into optimized schedules for flexible assets.
Why? Planning ahead allows flexible assets to serve the whole system with their flexibility, e.g. by shifting energy consumption to other times.
For the asset owners, this creates CO₂ savings but also monetary value (e.g. through self-consumption, dynamic tariffs and grid incentives).


.. image:: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/simple-flexEMS.png 
    :align: center
..    :scale: 40%


However, developing apps & services around energy flexibility is expensive work. FlexMeasures is designed to be developer-friendly, which helps you to go to market quickly, while keeping the costs of software development at bay. 
FlexMeasures supports:

- Real-time data integration & intelligence 
- Model data well ― units, time resolution & uncertainty (of forecasts)
- Faster app-building (API/UI/CLI, plugin & multi-tenancy support)

More on this in :ref:`dev_tooling`. FlexMeasures proudly is an incubation project at `the Linux Energy Foundation <https://www.lfenergy.org/>`_. Also, read more on where FlexMeasures is useful in :ref:`use_cases`.


A quick glance at usage
------------------------

A tiny, but complete example: Let's install FlexMeasures from scratch. Then, using only the terminal (FlexMeasures of course also has APIs for all of this), load hourly prices and optimize a 12h-schedule for a battery that is half full at the beginning. Finally, look at our new schedule.

.. code-block:: console

    $ pip install flexmeasures  # FlexMeasures can also be run via Docker
    $ docker pull postgres; docker run --name pg-docker -e POSTGRES_PASSWORD=docker -e POSTGRES_DB=flexmeasures-db -d -p 5433:5432 postgres:latest 
    $ export SQLALCHEMY_DATABASE_URI="postgresql://postgres:docker@127.0.0.1:5433/flexmeasures-db" && export SECRET_KEY=notsecret 
    $ flexmeasures db upgrade  # create tables
    $ flexmeasures add toy-account --kind battery  # setup account incl. a user, battery (ID 1) and market (ID 2)
    $ flexmeasures add beliefs --sensor-id 2 --source toy-user prices-tomorrow.csv --timezone utc  # load prices, also possible per API
    $ flexmeasures add schedule for-storage --sensor-id 1 --consumption-price-sensor 2 \
        --start ${TOMORROW}T07:00+01:00 --duration PT12H \
        --soc-at-start 50% --roundtrip-efficiency 90%  # this is also possible per API
    $ flexmeasures show beliefs --sensor-id 1 --start ${TOMORROW}T07:00:00+01:00 --duration PT12H  # also visible per UI, of course

We discuss this in more depth at :ref:`tut_toy_schedule`.


.. _use_cases:

Use cases
-----------

Here are a few relevant areas in which FlexMeasures can help you:

- E-mobility (smart :abbr:`EV (Electric Vehicle)` charging, :abbr:`V2G (Vehicle to Grid)`, :abbr:`V2H (Vehicle to Home)`)
- Heating (heat pump control)
- Industry (best running times for processes with buffering capacity)

You decide what to optimize for ― prices, CO₂, peaks.

It becomes even more interesting to use FlexMeasures in *integrated scenarios* with increased complexity. For example, in modern domestic/office settings that combine solar panels, electric heating and EV charging, in industry settings that optimize for self-consumption of local solar panels, or when consumers can engage with multiple markets simultaneously.

In these cases, our goal is that FlexMeasures helps you to achieve *"value stacking"*, which is often required to achieve a positive business case. Multiple sources of value can combine with multiple types of assets.

As possible users, we see energy service companies (ESCOs) who want to build real-time apps & services around energy flexibility for their customers, or medium/large industrials who are looking for support in their internal digital tooling.

However, even small companies and hobby projects might find FlexMeasures useful! We are constantly improving the ease of use. 

FlexMeasures can be used as your EMS, but it can also integrate with existing systems as a smart backend, or as an add-on to deal with energy flexibility specifically.

The image below shows how FlexMeasures, with the help of plugins fitted for a given use case, turns data into optimized schedules:

.. image:: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/overview-flexEMS.png 
    :align: center
..    :scale: 40%



A possible road to start using FlexMeasures in your operation
---------------------------------------------------------------

We make FlexMeasures, so that software developers are as productive with energy optimization as possible. Because we are developers ourselves, we know that it takes a couple smaller steps to engage with new technology. 

Your journey, from dipping your toes in the water towards being a happy FlexMeasures power user, could look like this:

1. Quickstart ― Find an optimized schedule for your flexible asset, like a battery, with standard FlexMeasures tooling. This is basically what the from-scratch tutorial above does. All you need are 10 minutes and a CSV file with prices to optimise against.
2. Automate ― get the prices from an open API, for instance `ENTSO-E <https://transparency.entsoe.eu/>`_ (using a plugin like `flexmeasures-entsoe <https://github.com/SeitaBV/flexmeasures-entsoe>`_), and run the scheduler regularly in a cron job.
3. Integrate ― Load the schedules via FlexMeasures' API, so you can directly control your assets and/or show them within your own frontend.
4. Customize ― Load other data (e.g. your solar production or weather forecasts via `flexmeasures-openweathermap <https://github.com/SeitaBV/flexmeasures-openweathermap/>`_). Adapt the algorithms, e.g. do your own forecasting or tweak the standard scheduling algorithm so it optimizes what you care about. Or write a plugin for accessing a new kind of market. The opportunities are endless!



Where to start reading?
--------------------------

You (the reader) might be a user connecting with a FlexMeasures server or working on hosting FlexMeasures. Maybe you are planning to develop a plugin or even core functionality. In :ref:`getting_started`, we have some helpful tips how to dive into this documentation!


.. _dev_tooling:

Developer support
------------------------

FlexMeasures is designed to help with three basic needs of developers in the energy flexibility domain:


I need help with integrating real-time data and continuously computing new data
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

FlexMeasures is designed to make decisions based on data in an automated way. Data pipelining and dedicated machine learning tooling is crucial.

- API/CLI functionality to read in time series data
- Extensions for integrating 3rd party data, e.g. from `ENTSO-E <https://github.com/SeitaBV/flexmeasures-entsoe>`_ or `OpenWeatherMap <https://github.com/SeitaBV/flexmeasures-openweathermap>`_
- Forecasting for the upcoming hours
- Schedule optimization for flexible assets


It's hard to correctly model data with different sources, resolutions, horizons and even uncertainties
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Much developer time is spent correcting data and treating it correctly, so that you know you are computing on the right knowledge.

FlexMeasures is built on the `timely-beliefs framework <https://github.com/SeitaBV/timely-beliefs>`_, so we model this real-world aspect accurately:

- Expected data properties are explicit (e.g. unit, time resolution)
- Incoming data is converted to fitting unit and time resolution automatically
- FlexMeasures also stores who thought that something happened (or that it will happen), and when they thought so
- Uncertainty can be modelled (useful for forecasting)


I want to build new features quickly, not spend days solving basic problems
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Building customer-facing apps & services is where developers make impact. We make their work easy.

- FlexMeasures has well-documented API endpoints and CLI commands to interact with its model and data
- You can extend it easily with your own logic by writing plugins
- A backend UI shows you your assets in maps and your data in plots. There is also support for plots to be available per API, for integration in your own frontend
- Multi-tenancy ― model multiple accounts on one server. Data is only seen/editable by authorized users in the right account


For more on FlexMeasures services, read :ref:`services`. Or head right over to :ref:`getting_started`.


Using FlexMeasures benefits operators as well as asset owners, by allowing for automation, insight, autonomy and profit sharing.
For more on benefits, consult :ref:`benefits`.

FlexMeasures is compliant with the `Universal Smart Energy Framework (USEF) <https://www.usef.energy/>`_.
Therefore, this documentation uses USEF terminology, e.g. for role definitions.
In this context, the intended users of FlexMeasures are a Supplier (energy company) and its Prosumers (asset owners who have energy contracts with that Supplier).
The platform operator of FlexMeasures can be an Aggregator.


.. toctree::
   :maxdepth: 1
   :hidden:

   getting-started
   get-in-touch
   changelog


.. toctree::
    :caption: Concepts
    :maxdepth: 1

    concepts/benefits
    concepts/inbuilt-smart-functionality
    concepts/algorithms
    concepts/security_auth
    concepts/device_scheduler


.. toctree::
    :caption: Tutorials
    :maxdepth: 1
    
    tut/installation
    tut/toy-example-setup
    tut/toy-example-from-scratch
    tut/toy-example-expanded
    tut/toy-example-process
    tut/toy-example-reporter
    tut/installation
    tut/posting_data
    tut/forecasting_scheduling
    tut/building_uis

.. toctree::
    :caption: The in-built UI
    :maxdepth: 1

    views/dashboard
    views/asset-data
    views/admin

.. toctree::
    :caption: The API 
    :maxdepth: 1

    api/introduction
    api/notation
    api/v3_0
    api/dev
    api/change_log

.. toctree::
    :caption: The CLI 
    :maxdepth: 1

    cli/commands
    cli/change_log


.. toctree::
    :caption: Hosting FlexMeasures
    :maxdepth: 1

    host/docker
    host/data
    host/deployment
    configuration
    host/queues
    host/error-monitoring
    host/modes


.. toctree::
    :caption: Developing Plugins
    :maxdepth: 1

    plugin/introduction
    plugin/showcase
    plugin/customisation


.. toctree::
    :caption: Developing on FlexMeasures
    :maxdepth: 1

    dev/introduction
    dev/api
    dev/ci
    dev/auth
    dev/docker-compose


.. autosummary::
   :caption: Code Documentation
   :toctree: _autosummary/
   :template: custom-module-template.rst
   :recursive:

   flexmeasures.api
   flexmeasures.app
   flexmeasures.auth
   flexmeasures.cli
   flexmeasures.data
   flexmeasures.ui
   flexmeasures.utils


.. Code documentation
.. ------------------

.. Go To :ref:`source`.



.. Indices and tables
.. ==================

.. * :ref:`genindex`
.. * :ref:`modindex`
.. * :ref:`search`

