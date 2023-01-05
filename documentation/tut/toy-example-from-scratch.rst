.. _tut_toy_schedule:

Toy example: Scheduling a battery, from scratch
===============================================

Let's walk through an example from scratch! We'll ... 

- install FlexMeasures
- create an account with a battery asset
- load hourly prices
- optimize a 12h-schedule for a battery that is half full

What do you need? Your own computer, with one of two situations: Either you have `Docker <https://www.docker.com/>`_ or your computer supports Python 3.8+, pip and PostgresDB. The former might be easier, see the installation step below. But you choose.

Below are the ``flexmeasures`` CLI commands we'll run, and which we'll explain step by step. There are some other crucial steps for installation and setup, so this becomes a complete example from scratch, but this is the meat:

.. code-block:: console

    # setup an account with a user, a battery (Id 2) and a market (Id 3)
    $ flexmeasures add toy-account --kind battery
    # load prices to optimise the schedule against
    $ flexmeasures add beliefs --sensor-id 3 --source toy-user prices-tomorrow.csv --timezone utc
    # make the schedule
    $ flexmeasures add schedule for-storage --sensor-id 2 --consumption-price-sensor 3 \
        --start ${TOMORROW}T07:00+01:00 --duration PT12H \
        --soc-at-start 50% --roundtrip-efficiency 90%


Okay, let's get started!


.. note:: You can copy the commands by hovering on the top right corner of code examples. You'll copy only the commands, not the output!

Install Flexmeasures and the database
---------------------------------------

.. tabs::

  .. tab:: Docker

        If `docker <https://www.docker.com/>`_ is running on your system, you're good to go. Otherwise, see `here <https://docs.docker.com/get-docker/>`_.

        We start by installing the FlexMeasures platform, and then use Docker to run a postgres database and tell FlexMeasures to create all tables.

        .. code-block:: console

            $ docker pull lfenergy/flexmeasures:latest
            $ docker pull postgres
            $ docker network create flexmeasures_network
            $ docker run --rm --name flexmeasures-tutorial-db -e POSTGRES_PASSWORD=fm-db-passwd -e POSTGRES_DB=flexmeasures-db -d --network=flexmeasures_network postgres:latest 
            $ docker run --rm --name flexmeasures-tutorial-fm --env SQLALCHEMY_DATABASE_URI=postgresql://postgres:fm-db-passwd@flexmeasures-tutorial-db:5432/flexmeasures-db --env SECRET_KEY=notsecret --env FLASK_ENV=development --env LOGGING_LEVEL=INFO -d --network=flexmeasures_network -p 5000:5000 lfenergy/flexmeasures
            $ docker exec flexmeasures-tutorial-fm bash -c "flexmeasures db upgrade"

        Now - what's *very important* to remember is this: The rest of this tutorial will happen *inside* the ``flexmeasures-tutorial-fm`` container! This is how you hop inside the container and run a terminal there:

        .. code-block:: console

            $ docker exec -it flexmeasures-tutorial-fm bash

        To leave the container session, hold CTRL-C or type "exit".

        To stop the containers, you can type
        
        .. code-block:: console
        
            $ docker stop flexmeasures-tutorial-db
            $ docker stop flexmeasures-tutorial-fm

        .. note:: A tip on Linux/macOS ― You might have the ``docker`` command, but need `sudo` rights to execute it. ``alias docker='sudo docker'`` enables you to still run this tutorial.

        .. note:: Got docker-compose? You could run this tutorial with 5 containers :) ― Go to :ref:`docker-compose-tutorial`.

  .. tab:: On your PC
        
        This example is from scratch, so we'll assume you have nothing prepared but a (Unix) computer with Python (3.8+) and two well-known developer tools, `pip <https://pip.pypa.io>`_ and `postgres <https://www.postgresql.org/download/>`_.

        We'll create a database for FlexMeasures:

        .. code-block:: console

            sudo -i -u postgres
            createdb -U postgres flexmeasures-db
            createuser --pwprompt -U postgres flexmeasures-user      # enter your password, we'll use "fm-db-passwd"
            exit

        Then, we can install FlexMeasures itself, set some variables and tell FlexMeasures to create all tables:

        .. code-block:: console

            $ pip install flexmeasures
            $ export SQLALCHEMY_DATABASE_URI="postgresql://flexmeasures-user:fm-db-passwd@localhost:5432/flexmeasures-db" SECRET_KEY=notsecret LOGGING_LEVEL="INFO" DEBUG=0
            $ flexmeasures db upgrade 

        .. note:: When installing with ``pip``, on some platforms problems might come up (e.g. macOS, Windows). One reason is that FlexMeasures requires some libraries with lots of C code support (e.g. Numpy). One way out is to use Docker, which uses a prepared Linux image, so it'll definitely work.


Add some structural data
---------------------------------------

The data we need for our example is both structural (e.g. a company account, a user, an asset) and numeric (we want market prices to optimize against).

Let's create the structural data first.

FlexMeasures offers a command to create a toy account with a battery:

.. code-block:: console

    $ flexmeasures add toy-account --kind battery

    Toy account Toy Account with user toy-user@flexmeasures.io created successfully. You might want to run `flexmeasures show account --id 1`
    The sensor for battery (dis)charging is <Sensor 2: discharging, unit: MW res.: 0:15:00>.
    The sensor for Day ahead prices is <Sensor 3: Day ahead prices, unit: EUR/MWh res.: 1:00:00>.

And with that, we're done with the structural data for this tutorial! 

If you want, you can inspect what you created:

.. code-block:: console

    $ flexmeasures show account --id 1                       
    
    =============================
    Account Toy Account (ID:1):
    =============================

    Account has no roles.

    All users:
    
      Id  Name      Email                     Last Login    Roles
    ----  --------  ------------------------  ------------  -------------
       1  toy-user  toy-user@flexmeasures.io                account-admin

    All assets:
    
      Id  Name          Type      Location
    ----  ------------  --------  -----------------
       3  toy-battery   battery   (52.374, 4.88969)
       2  toy-building  building  (52.374, 4.88969)
       1  toy-solar     solar     (52.374, 4.88969)

    $ flexmeasures show asset --id 3
    
    ===========================
    Asset toy-battery (ID:3):
    ===========================

    Type     Location           Attributes
    -------  -----------------  ---------------------
    battery  (52.374, 4.88969)  capacity_in_mw:0.5
                                min_soc_in_mwh:0.05
                                max_soc_in_mwh:0.45

    All sensors in asset:
    
      Id  Name      Unit    Resolution    Timezone          Attributes
    ----  --------  ------  ------------  ----------------  ------------
       2  charging  MW      15 minutes    Europe/Amsterdam


Yes, that is quite a large battery :)

.. note:: Obviously, you can use the ``flexmeasures`` command to create your own, custom account and assets. See :ref:`cli`. And to create, edit or read asset data via the API, see :ref:`v3_0`.

We can also look at the battery asset in the UI of FlexMeasures (in Docker, the FlexMeasures web server already runs, on your PC you can start it with ``flexmeasures run``).
Visit `http://localhost:5000/assets <http://localhost:5000/assets>`_ (username is "toy-user@flexmeasures.io", password is "toy-password") and select "toy-battery":

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/asset-view.png
    :align: center

.. note:: You won't see the map tiles, as we have not configured the :ref:`MAPBOX_ACCESS_TOKEN`. If you have one, you can configure it via ``flexmeasures.cfg`` (for Docker, see :ref:`docker_configuration`).


.. _tut_toy_schedule_price_data:

Add some price data
---------------------------------------

Now to add price data. First, we'll create the csv file with prices (EUR/MWh, see the setup for sensor 3 above) for tomorrow.

.. code-block:: console

    $ TOMORROW=$(date --date="next day" '+%Y-%m-%d')
    $ echo "Hour,Price                                      
    $ ${TOMORROW}T00:00:00,10
    $ ${TOMORROW}T01:00:00,11
    $ ${TOMORROW}T02:00:00,12
    $ ${TOMORROW}T03:00:00,15
    $ ${TOMORROW}T04:00:00,18
    $ ${TOMORROW}T05:00:00,17
    $ ${TOMORROW}T06:00:00,10.5
    $ ${TOMORROW}T07:00:00,9
    $ ${TOMORROW}T08:00:00,9.5
    $ ${TOMORROW}T09:00:00,9
    $ ${TOMORROW}T10:00:00,8.5
    $ ${TOMORROW}T11:00:00,10
    $ ${TOMORROW}T12:00:00,8
    $ ${TOMORROW}T13:00:00,5
    $ ${TOMORROW}T14:00:00,4
    $ ${TOMORROW}T15:00:00,4
    $ ${TOMORROW}T16:00:00,5.5
    $ ${TOMORROW}T17:00:00,8
    $ ${TOMORROW}T18:00:00,12
    $ ${TOMORROW}T19:00:00,13
    $ ${TOMORROW}T20:00:00,14
    $ ${TOMORROW}T21:00:00,12.5
    $ ${TOMORROW}T22:00:00,10
    $ ${TOMORROW}T23:00:00,7" > prices-tomorrow.csv

This is time series data, in FlexMeasures we call "beliefs". Beliefs can also be sent to FlexMeasures via API or imported from open data hubs like `ENTSO-E <https://github.com/SeitaBV/flexmeasures-entsoe>`_ or `OpenWeatherMap <https://github.com/SeitaBV/flexmeasures-openweathermap>`_. However, in this tutorial we'll show how you can read data in from a CSV file. Sometimes that's just what you need :)

.. code-block:: console

    $ flexmeasures add beliefs --sensor-id 3 --source toy-user prices-tomorrow.csv --timezone utc
    Successfully created beliefs

In FlexMeasures, all beliefs have a data source. Here, we use the username of the user we created earlier. We could also pass a user ID, or the name of a new data source we want to use for CLI scripts.

.. note:: Attention: We created and imported prices where the times have no time zone component! That happens a lot. Here, we localized the data to UTC time. So if you are in Amsterdam time, the start time for the first price, when expressed in your time zone, is actually `2022-03-03 01:00:00+01:00`.

Let's look at the price data we just loaded:

.. code-block:: console

    $ flexmeasures show beliefs --sensor-id 3 --start ${TOMORROW}T01:00:00+01:00 --duration PT24H
    Beliefs for Sensor 'Day ahead prices' (Id 3).
    Data spans a day and starts at 2022-03-03 01:00:00+01:00.
    The time resolution (x-axis) is an hour.
    ┌────────────────────────────────────────────────────────────┐
    │         ▗▀▚▖                                               │ 18EUR/MWh
    │         ▞  ▝▌                                              │ 
    │        ▐    ▚                                              │ 
    │       ▗▘    ▐                                              │ 
    │       ▌      ▌                                     ▖       │ 
    │      ▞       ▚                                  ▗▄▀▝▄      │ 
    │     ▗▘       ▐                                ▗▞▀    ▚     │ 13EUR/MWh
    │   ▗▄▘         ▌                              ▐▘       ▚    │ 
    │ ▗▞▘           ▚                              ▌         ▚   │ 
    │▞▘             ▝▄           ▗                ▐          ▝▖  │ 
    │                 ▚▄▄▀▚▄▄   ▞▘▚               ▌           ▝▖ │ 
    │                        ▀▀▛   ▚             ▐             ▚ │ 
    │                               ▚           ▗▘              ▚│ 8EUR/MWh
    │                                ▌         ▗▘               ▝│ 
    │                                ▝▖        ▞                 │ 
    │                                 ▐▖     ▗▀                  │ 
    │                                  ▝▚▄▄▄▄▘                   │ 
    └────────────────────────────────────────────────────────────┘
            5           10           15           20
                        ██ Day ahead prices



Again, we can also view these prices in the `FlexMeasures UI <http://localhost:5000/sensors/3/>`_:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-prices.png
    :align: center

.. note:: Technically, these prices for tomorrow may be forecasts (depending on whether you are running through this tutorial before or after the day-ahead market's gate closure). You can also use FlexMeasures to compute forecasts yourself. See :ref:`tut_forecasting_scheduling`.


Make a schedule
---------------------------------------

Finally, we can create the schedule, which is the main benefit of FlexMeasures (smart real-time control).

We'll ask FlexMeasures for a schedule for our charging sensor (Id 2). We also need to specify what to optimise against. Here we pass the Id of our market price sensor (3).
To keep it short, we'll only ask for a 12-hour window starting at 7am. Finally, the scheduler should know what the state of charge of the battery is when the schedule starts (50%) and what its roundtrip efficiency is (90%).

.. code-block:: console

    $ flexmeasures add schedule for-storage --sensor-id 2 --consumption-price-sensor 3 \
        --start ${TOMORROW}T07:00+01:00 --duration PT12H \
        --soc-at-start 50% --roundtrip-efficiency 90%
    New schedule is stored.

Great. Let's see what we made:

.. code-block:: console

    $ flexmeasures show beliefs --sensor-id 2 --start ${TOMORROW}T07:00:00+01:00 --duration PT12H
    Beliefs for Sensor 'discharging' (Id 2).
    Data spans 12 hours and starts at 2022-03-04 07:00:00+01:00.
    The time resolution (x-axis) is 15 minutes.
    ┌────────────────────────────────────────────────────────────┐
    │   ▐                      ▐▀▀▌                           ▛▀▀│ 
    │   ▞▌                     ▞  ▐                           ▌  │ 0.4MW
    │   ▌▌                     ▌  ▐                          ▐   │ 
    │  ▗▘▌                     ▌  ▐                          ▐   │ 
    │  ▐ ▐                    ▗▘  ▝▖                         ▐   │ 
    │  ▞ ▐                    ▐    ▌                         ▌   │ 0.2MW
    │ ▗▘ ▐                    ▐    ▌                         ▌   │ 
    │ ▐  ▝▖                   ▌    ▚                        ▞    │ 
    │▀▘───▀▀▀▀▀▀▀▀▀▀▀▀▀▀▌────▐─────▝▀▀▀▀▀▀▀▀▜─────▐▀▀▀▀▀▀▀▀▀─────│ 0MW
    │                   ▌    ▞              ▐    ▗▘              │ 
    │                   ▚    ▌              ▐    ▐               │ 
    │                   ▐   ▗▘              ▝▖   ▌               │ -0.2MW
    │                   ▐   ▐                ▌   ▌               │ 
    │                   ▐   ▐                ▌  ▗▘               │ 
    │                    ▌  ▞                ▌  ▐                │ 
    │                    ▌  ▌                ▐  ▐                │ -0.4MW
    │                    ▙▄▄▌                ▐▄▄▞                │ 
    └────────────────────────────────────────────────────────────┘
            10           20           30          40
                            ██ discharging


Here, negative values denote output from the grid, so that's when the battery gets charged. 

We can also look at the charging schedule in the `FlexMeasures UI <http://localhost:5000/sensors/2/>`_ (reachable via the asset page for the battery):

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-charging.png
    :align: center

Recall that we only asked for a 12 hour schedule here. We started our schedule *after* the high price peak (at 5am) and it also had to end *before* the second price peak fully realised (at 9pm). Our scheduler didn't have many opportunities to optimize, but it found some. For instance, it does buy at the lowest price (around 3pm) and sells it off when prices start rising again (around 6pm).


.. note:: The ``flexmeasures add schedule for-storage`` command also accepts state-of-charge targets, so the schedule can be more sophisticated. But that is not the point of this tutorial. See ``flexmeasures add schedule for-storage --help``. 
