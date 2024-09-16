Welcome to the FlexMeasures documentation!
===================================================================

*FlexMeasures* is an intelligent EMS to optimize behind-the-meter energy flexibility.
Build your smart energy apps & services with FlexMeasures as backend for real-time orchestration! 

The problem FlexMeasures helps you to solve is: **What are the best times to power flexible assets, such as batteries or heat pumps?**

In a nutshell, FlexMeasures turns data into optimized schedules for flexible assets.
*Why?* Planning ahead allows flexible assets to serve the whole system with their flexibility, e.g. by shifting energy consumption to more optimal times. For the asset owners, this creates CO₂ savings but also monetary value (e.g. through self-consumption, dynamic tariffs and grid incentives).


.. image:: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/simple-flexEMS.png 
    :align: center
..    :scale: 40%

FlexMeasures is written in Python, and runs on Flask and Postgres.
We aim to create developer-friendly technology that saves time in developing complex services.
Read more on this in :ref:`dev_why`.

FlexMeasures proudly is an incubation project at `the Linux Energy Foundation <https://www.lfenergy.org/>`_.


A quick glance 
----------------

The main purpose of FlexMeasures is to create optimized schedules. Let's have a quick glance at what that looks like in the UI and what a code implementation would be like:

.. tabs::

    .. tab:: Battery optimized by price

        .. image:: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/tut/toy-schedule/asset-view-without-solar.png
            :target: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/tut/toy-schedule/asset-view-without-solar.png
            :align: center
        ..    :scale: 40%
    
    .. tab:: Same but constrained by solar

        .. image:: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/tut/toy-schedule/asset-view-with-solar.png
            :target: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/tut/toy-schedule/asset-view-with-solar.png
            :align: center
        ..    :scale: 40%


    .. tab:: Code example

        A tiny, but complete example (corresponding to the left tab): Let's install FlexMeasures from scratch. Then, using only the terminal (FlexMeasures of course also has APIs for all of this), load hourly prices and optimize a 12h-schedule for a battery that is half full at the beginning. Finally, we'll display our new schedule in the terminal.

        .. code-block:: console

            $ pip install flexmeasures  # FlexMeasures can also be run via Docker
            $ docker pull postgres; docker run --name pg-docker -e POSTGRES_PASSWORD=docker -e POSTGRES_DB=flexmeasures-db -d -p 5433:5432 postgres:latest 
            $ export SQLALCHEMY_DATABASE_URI="postgresql://postgres:docker@127.0.0.1:5433/flexmeasures-db" && export SECRET_KEY=notsecret 
            $ flexmeasures db upgrade  # create tables
            $ flexmeasures add toy-account --kind battery  # setup account incl. a user, battery (ID 2) and market (ID 1)
            $ flexmeasures add beliefs --sensor 2 --source toy-user prices-tomorrow.csv --timezone utc  # load prices, also possible per API
            $ flexmeasures add schedule for-storage --sensor 2 --consumption-price-sensor 1 \
                --start ${TOMORROW}T07:00+01:00 --duration PT12H \
                --soc-at-start 50% --roundtrip-efficiency 90%  # this is also possible per API
            $ flexmeasures show beliefs --sensor 2 --start ${TOMORROW}T07:00:00+01:00 --duration PT12H  # also visible per UI, of course
    

A short explanation of the optimization shown above: This battery is optimized to buy power cheaply and sell it at expensive times - the red-dotted line is what FlexMeasures computed to be the best schedule, given all knowledge (in this case, the prices shown in blue). However, in the example in the middle tab, the battery has to store local solar power as well (orange line), which constrains how much it can do with its capacity (that's why the schedule is limited in capacity and thus cycling less energy overall than on the left).

Want to read more about the example case shown here? We discuss this in more depth at :ref:`tut_toy_schedule` and the tutorials that build on that.


What FlexMeasures does
-----------------------

.. _usage:

.. tabs::

  .. tab:: Main functionality

    - Scheduling
        The main purpose of FlexMeasures is to create optimized schedules. That's also what the "quick glance" section above focuses on. Everything else supports this main purpose. FlexMeasures provides in-built schedulers for storage and processes. Schedulers solve optimization problems for you and are highly customizable to the situation at hand. Read more at :ref:`scheduling` and, for hands-on introductions, at :ref:`tut_toy_schedule` and :ref:`tut_toy_schedule_process`. 
    - Reporting
        FlexMeasures needs to give users an idea of its effects and outcomes. For instance, computing the energy costs are an important use case. But also creating intermediate data for your scheduler can be a crucial feature (e.g. the allowed headroom for a battery is the difference between the grid connection capacity and the PV power). Read more at :ref:`reporting` and :ref:`tut_toy_schedule_reporter`.
    - Forecasting
        Optimizing the future (by scheduling) requires some predictions. Several predictions can be gotten from third parties (e.g. weather conditions, for which we wrote `a plugin <https://github.com/SeitaBV/flexmeasures-openweathermap>`_), others need to be done manually. FlexMeasures provides some support for this (read more at :ref:`forecasting` and :ref:`tut_forecasting_scheduling`), but you can also create predictions with one of the many excellent tools out there and feed them into FlexMeasures.
    - Monitoring
        As FlexMeasures is a real-time platform, processing data and computing new schedules continuously, hosting it requires to be notified when things go wrong. There is in-built :ref:`host_error_monitoring` for tracking connection problems and tasks that did not finish correctly. Also, you can connect to Sentry. We have `further plans to monitor data quality <https://github.com/FlexMeasures/flexmeasures/projects/12>`_.

  .. tab:: Interfacing with FlexMeasures

    - API
        FlexMeasures runs in the cloud (although it can also run on-premise if needed, for instance as Docker container). Therefore, a well-supported REST-like API is crucial. You can add & retrieve data, trigger schedule computations and even add and edit the structure (of assets and sensors). Read more at :ref:`api_introduction`.  
    - UI
        We built a user interface for FlexMeasures, so assets, data and schedules can be inspected by devs, hosters and analysts. You can start with :ref:`_dashboard` to get an idea. We expect that real energy flexibility services will come with their own UI, maybe as they are connecting FlexMeasures as a smart backend to an existing user-facing ESCO platform. In these cases, the API is more useful. However, FlexMeasures can provide its data plots and visualizations through the API in these cases, see :ref:`tut_building_uis`.
    - CLI
        For the engineers hosting FlexMeasures, a command-line interface is crucial. We developed a range of :ref:`cli` based on the ``flexmeasures`` directive (see also the code example above), so that DevOps personnel can administer accounts & users, load & review data and heck on computation jobs. The CLI is also useful to automate calls to third party APIs (via CRON jobs for instance) ― this is usually done when plugins add their own ``flexmeasures`` commands. 
    - FlexMeasures Client
        For automating the interaction with FlexMeasures from local sites (e.g. from a smart gateway - think RaspberryPi or higher-level), we created `the FlexMeasures Client <https://github.com/FlexMeasures/flexmeasures-client>`_. The Flexmeasures Client package provides functionality for authentication, posting sensor data, triggering schedules and retrieving schedules from a FlexMeasures instance through the API. 


.. _use_cases_and_users:

Use cases & Users
-----------

.. tabs::

  .. tab:: Use cases

        Here are a few relevant areas in which FlexMeasures can help you:

        - E-mobility (smart :abbr:`EV (Electric Vehicle)` charging, :abbr:`V2G (Vehicle to Grid)`, :abbr:`V2H (Vehicle to Home)`)
        - Heating (heat pump control, in combination with heat buffers)
        - Industry (best running times for processes with buffering capacity)

        You decide what to optimize for ― prices, CO₂, peaks.

        It becomes even more interesting to use FlexMeasures in *integrated scenarios* with increased complexity. For example, in modern domestic/office settings that combine solar panels, electric heating and EV charging, in industry settings that optimize for self-consumption of local solar panels, or when consumers can engage with multiple markets simultaneously.

        In these cases, our goal is that FlexMeasures helps you to achieve *"value stacking"*, which is often required to achieve a positive business case. Multiple sources of value can combine with multiple types of assets.

  .. tab:: Users

        As possible users, we see energy service companies (ESCOs) who want to build real-time apps & services around energy flexibility for their customers, or medium/large industrials who are looking for support in their internal digital tooling.

        However, even small companies and hobby projects might find FlexMeasures useful! We are constantly improving the ease of use.

        Within these organizations, several kinds of engineers might be working with FlexMeasures: gateway installers, ESCO data engineers and service developers.

        FlexMeasures can be used as your EMS, but it can also integrate with existing systems as a smart backend ― an add-on to deal with energy flexibility specifically.

        The image below shows the FlexMeasures eco-system and the users, where the server (this repository) is supported by the FlexMeasures client and several plugins to implement many kinds of services with optimized schedules:

        .. image:: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/FlexMeasures-IntegrationMap.drawio.png 
            :target: https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/FlexMeasures-IntegrationMap.drawio.png
            :align: center
        ..    :scale: 40%

        This image should also make clear how to extend FlexMeasures on the edges to make it work for your exact use case ― by gateway integration, plugins and using FlexMeasures via its API.



Where to start reading?
--------------------------

You (the reader) might be a user connecting with a FlexMeasures server or working on hosting FlexMeasures. Maybe you are planning to develop a plugin or even core functionality. Maybe you are a CTO looking for a suitable open source framework.

In :ref:`getting_started`, we have some helpful tips how to dive into this documentation!




.. toctree::
   :maxdepth: 1
   :hidden:

   getting-started
   get-in-touch
   changelog


.. toctree::
    :caption: Features
    :maxdepth: 1
    
    features/scheduling
    features/forecasting
    features/reporting

.. toctree::
    :caption: Tutorials
    :maxdepth: 1
    
    tut/toy-example-setup
    tut/toy-example-from-scratch
    tut/toy-example-expanded
    tut/flex-model-v2g
    tut/toy-example-process
    tut/toy-example-reporter
    tut/posting_data
    tut/forecasting_scheduling
    tut/building_uis


.. toctree::
    :caption: Concepts
    :maxdepth: 1

    concepts/flexibility
    concepts/data-model
    concepts/security_auth
    concepts/device_scheduler


.. toctree::
    :caption: The in-built UI
    :maxdepth: 1

    views/dashboard
    views/asset-data
    views/account
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

    host/installation
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

    dev/why
    dev/setup-and-guidelines
    dev/api
    dev/ci
    dev/auth
    dev/docker-compose
    dev/dependency-management


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

