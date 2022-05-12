Welcome to the FlexMeasures documentation!
===================================================================

*FlexMeasures is the intelligent & developer-friendly EMS to support real-time energy flexibility apps, rapidly and scalable.*

In a world with renewable energy, flexibility is crucial and valuable, e.g. for demand response.
Planning ahead allows flexible assets like batteries or heat pumps to serve the whole system with their flexibility,
e.g. by shifting or curtailing energy use.

In a nutshell, FlexMeasures turns data into optimized schedules for flexible assets.

However, developing energy flexibility services is expensive work. FlexMeasures is designed to be developer-friendly, which helps you to go to market quickly, while keeping the costs of software development at bay. 
FlexMeasures supports:

- Real-time data intelligence & integration
- Uncertainty models
- App-building (API/UI/CLI & plugin support)

More on this in :ref:`dev_tooling`. FlexMeasures proudly is an incubation project at `the Linux Energy Foundation <https://www.lfenergy.org/>`_. More on where it is useful in :ref:`use_cases`.


A quick glance at usage
------------------------

A tiny, but complete example: Let's install FlexMeasures from scratch. Then, using only the terminal (FlexMeasures of course also has APIs for all of this), load hourly prices and optimize a 12h-schedule for a battery that is half full at the beginning. Finally, look at our new schedule.

.. code-block:: console

    $ pip install flexmeasures  # FlexMeasures can also be run via Docker
    $ docker pull postgres; docker run --name pg-docker -e POSTGRES_PASSWORD=docker -e POSTGRES_DB=flexmeasures-db -d -p 5433:5432 postgres:latest 
    $ export SQLALCHEMY_DATABASE_URI="postgresql://postgres:docker@127.0.0.1:5433/flexmeasures-db" && export SECRET_KEY=notsecret 
    $ flexmeasures db upgrade  # create tables
    $ flexmeasures add toy-account --kind battery  # setup account & a user, a battery (Id 2) and a market (Id 3)
    $ flexmeasures add beliefs --sensor-id 3 --source toy-user prices-tomorrow.csv  # load prices, also possible per API
    $ flexmeasures add schedule --sensor-id 2 --optimization-context-id 3 \
        --start ${TOMORROW}T07:00+01:00 --duration PT12H \
        --soc-at-start 50% --roundtrip-efficiency 90%  # this is also possible per API
    $ flexmeasures show beliefs --sensor-id 2 --start ${TOMORROW}T07:00:00+01:00 --duration PT12H  # also visible per UI, of course

We discuss this in more depth at :ref:`tut_toy_schedule`.


.. _use_cases:

Use cases
-----------

Here are a few relevant areas in which FlexMeasures can help you:

- E-mobility (smart :abbr:`EV (Electric Vehicle)` charging, :abbr:`V2G (Vehicle to Grid)`, :abbr:`V2H (Vehicle to Home)`)
- Heating (heat pump control)
- Industry (best running times for processes with buffering capacity)

You decide what to optimize for ― prices, CO₂, peaks.

It becomes even more interesting to use FlexMeasures in integrated scenarios with increased complexity. For example, in modern domestic settings that combine solar panels, electric heating and EV charging, in industry settings that optimize for self-consumption of local solar panels, or when consumers can engage with multiple markets simultaneously.

As possible users, we see energy service companies (ESCOs) who want to build real-time apps & services around energy flexibility for their customers, or medium/large industrials who are looking for support in their internal digital tooling.

However, even small companies and hobby projects might find FlexMeasures useful! We are constantly improving the ease of use. 

FlexMeasures can be used as your EMS, but it can also integrate with existing systems as a smart backend, or as an add-on to deal with energy flexibility specifically.

The image below shows how FlexMeasures, with the help of plugins fitted for a given use case, turns data into optimized schedules:

.. image:: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/overview-flexEMS.png 
    :align: center
..    :scale: 40%

You (the reader) might be a user connecting with a FlexMeasures server or working on hosting FlexMeasures. Maybe you are planning to develop a plugin or even core functionality. In :ref:`getting_started`, we have some helpful tips how to dive into this documentation!


A possible road to start using FlexMeasures in your operation
---------------------------------------------------------------

We make FlexMeasures, so that developers are as productive with energy optimization as possible. As we are developers ourselves, we know that it takes a couple smaller steps to engage with new technology. 

Your journey, from dipping your toes in the water towards being a happy FlexMeasures power user, could look like this:

1. Quickstart ― Find an optimized schedule for your flexible asset, like a battery, with standard FlexMeasures tooling. This is basically what the from-scratch tutorial above does. All you need are 10 minutes and a CSV file with prices to optimise against.
2. Automate ― get the prices from an open API, for instance `ENTSO-E <https://transparency.entsoe.eu/>`_ (using a plugin like `flexmeasures-entsoe <https://github.com/SeitaBV/flexmeasures-entsoe>`_), and run the scheduler regularly in a cron job.
3. Integrate ― Load the schedules via FlexMeasures' API, so you can directly control your assets and/or show them within your own frontend.
4. Customize ― Load other data (e.g. your solar production or weather forecasts via `flexmeasures-openweathermap <https://github.com/SeitaBV/flexmeasures-openweathermap/>`_. Adapt the algorithms, e.g. do your own forecasting or tweak the standard scheduling algorithm so it optimizes what you care about. Or write a plugin for accessing a new kind of market. The opportunities are endless!


.. _dev_tooling:

Developer support
------------------------

There are three ways in which FlexMeasures supports developers:

Real-time data intelligence & integration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Energy flexibility services need to interact multiple times per day or hour. We equipped FlexMeasures with:

- Support for real-time updates
- Forecasting for the upcoming hours
- Schedule optimization
- Extensions for integrating data, e.g. from `ENTSO-E <https://github.com/SeitaBV/flexmeasures-entsoe>`_ or `OpenWeatherMap <https://github.com/SeitaBV/flexmeasures-openweathermap>`_


Uncertainty models
^^^^^^^^^^^^^^^^^^^^

Dealing with uncertain forecasts and outcomes is crucial.

FlexMeasures is therefore built on the `timely-beliefs framework <https://github.com/SeitaBV/timely-beliefs>`_, so we model this real-world aspect accurately.


App building
^^^^^^^^^^^^^^^^^^
Building customer-facing apps & services is where developers make impact. We make their work easy.

- Well-documented API and CLI
- Plugin support (add your own logic)
- Backend UI and support for plotting
- Multi-tenancy


For more on FlexMeasures services, read :ref:`services`. Or head right over to :ref:`getting_started`.


Using FlexMeasures benefits operators as well as asset owners,
by allowing for automation, insight, autonomy and profit sharing.
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
    concepts/benefits_of_flex
    concepts/inbuilt-smart-functionality
    concepts/algorithms
    concepts/security_auth


.. toctree::
    :caption: Tutorials
    :maxdepth: 1
    
    tut/toy-example-from-scratch
    tut/installation
    tut/posting_data
    tut/forecasting_scheduling
    tut/building_uis

.. toctree::
    :caption: The in-built UI
    :maxdepth: 1

    views/dashboard
    views/admin

.. toctree::
    :caption: The API 
    :maxdepth: 1

    api/introduction
    api/notation
    api/v3_0
    api/v2_0
    api/v1_3
    api/v1_2
    api/v1_1
    api/v1
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
    configuration
    dev/api
    dev/ci
    dev/auth
    dev/docker-compose



Code documentation
------------------

Go To :ref:`source`.



.. Indices and tables
.. ==================

.. * :ref:`genindex`
.. * :ref:`modindex`
.. * :ref:`search`

