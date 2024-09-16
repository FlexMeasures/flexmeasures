.. _tut_install_load_data:

Toy example: Introduction and setup
===================================

This page is a starting point of a series of tutorials that will help you get practical experience with FlexMeasures.

Let's walk through an example from scratch! We'll ... 

- install FlexMeasures
- create an account
- load hourly prices

What do you need? Your own computer, with one of two situations: either you have `Docker <https://www.docker.com/>`_ or your computer supports Python 3.8+, pip and PostgresDB. The former might be easier, see the installation step below. But you choose.

Below are the ``flexmeasures`` CLI commands we'll run, and which we'll explain step by step. There are some other crucial steps for installation and setup, so this becomes a complete example from scratch, but this is the meat:

.. code-block:: bash

    # setup an account with a user, assets for battery & solar and an energy market (ID 1)
    $ flexmeasures add toy-account
    # load prices to optimise the schedule against
    $ flexmeasures add beliefs --sensor 1 --source toy-user prices-tomorrow.csv --timezone Europe/Amsterdam


Okay, let's get started!


.. note:: You can copy the commands by hovering on the top right corner of code examples. You'll copy only the commands, not the output!

Install Flexmeasures and the database
---------------------------------------

.. tabs::

  .. tab:: Docker

        If `docker <https://www.docker.com/>`_ is running on your system, you're good to go. Otherwise, see `here <https://docs.docker.com/get-docker/>`_.

        We start by installing the FlexMeasures platform, and then use Docker to run a postgres database and tell FlexMeasures to create all tables.

        .. code-block:: bash

            $ docker pull lfenergy/flexmeasures:latest
            $ docker pull postgres
            $ docker network create flexmeasures_network

        .. note:: A tip on Linux/macOS ― You might have the ``docker`` command, but need `sudo` rights to execute it.
                  ``alias docker='sudo docker'`` enables you to still run this tutorial.

        After running these commands, we can start the Postgres database and the FlexMeasures app with the following commands:

        .. code-block:: bash

            $ docker run --rm --name flexmeasures-tutorial-db -e POSTGRES_PASSWORD=fm-db-passwd -e POSTGRES_DB=flexmeasures-db -d --network=flexmeasures_network postgres:latest
            $ docker run --rm --name flexmeasures-tutorial-fm --env SQLALCHEMY_DATABASE_URI=postgresql://postgres:fm-db-passwd@flexmeasures-tutorial-db:5432/flexmeasures-db --env SECRET_KEY=notsecret --env FLEXMEASURES_ENV=development --env LOGGING_LEVEL=INFO -d --network=flexmeasures_network -p 5000:5000 lfenergy/flexmeasures

        When the app has started, the FlexMeasures UI should be available at http://localhost:5000 in your browser.

        .. include:: ../notes/macOS-docker-port-note.rst

        To establish the FlexMeasures database structure, execute:

        .. code-block:: bash

            $ docker exec flexmeasures-tutorial-fm bash -c "flexmeasures db upgrade"

        Now - what's *very important* to remember is this: The rest of this tutorial will happen *inside* the ``flexmeasures-tutorial-fm`` container! This is how you hop inside the container and run a terminal there:

        .. code-block:: bash

            $ docker exec -it flexmeasures-tutorial-fm bash

        To leave the container session, hold CTRL-D or type "exit".

        To stop the containers, you can type

        .. code-block:: bash

            $ docker stop flexmeasures-tutorial-db
            $ docker stop flexmeasures-tutorial-fm

        To start the containers again, do this (note that re-running the `docker run` commands above *deletes and re-creates* all data!):

        .. code-block:: bash

            $ docker start flexmeasures-tutorial-db
            $ docker start flexmeasures-tutorial-fm

        .. note:: Got docker-compose? You could run this tutorial with 5 containers :) ― Go to :ref:`docker-compose-tutorial`.

  .. tab:: On your PC

        This example is from scratch, so we'll assume you have nothing prepared but a (Unix) computer with Python (3.8+) and two well-known developer tools, `pip <https://pip.pypa.io>`_ and `postgres <https://www.postgresql.org/download/>`_.

        We'll create a database for FlexMeasures:

        .. code-block:: bash

            $ sudo -i -u postgres
            $ createdb -U postgres flexmeasures-db
            $ createuser --pwprompt -U postgres flexmeasures-user      # enter your password, we'll use "fm-db-passwd"
            $ exit

        Then, we can install FlexMeasures itself, set some variables and tell FlexMeasures to create all tables:

        .. code-block:: bash

            $ pip install flexmeasures
            $ export SQLALCHEMY_DATABASE_URI="postgresql://flexmeasures-user:fm-db-passwd@localhost:5432/flexmeasures-db" SECRET_KEY=notsecret LOGGING_LEVEL="INFO" DEBUG=0
            $ export FLEXMEASURES_ENV="development"
            $ flexmeasures db upgrade

        .. note:: When installing with ``pip``, on some platforms problems might come up (e.g. macOS, Windows). One reason is that FlexMeasures requires some libraries with lots of C code support (e.g. Numpy). One way out is to use Docker, which uses a prepared Linux image, so it'll definitely work.

        In case you want to re-run the tutorial, then it's recommended to delete the old database and create a fresh one. Run the following command to create a clean database with a new user, where it is optional. If you don't provide the user, then the default `postgres` user will be used to create the database.

        .. code-block:: bash

            $ make clean-db db_name=flexmeasures-db [db_user=flexmeasures]

        To start the web application, you can run:

        .. code-block:: bash

            $ flexmeasures run

        When started, the FlexMeasures UI should be available at http://localhost:5000 in your browser.

        .. include:: ../notes/macOS-port-note.rst


Add some structural data
---------------------------------------

The data we need for our example is both structural (e.g. a company account, a user, an asset) and numeric (we want market prices to optimize against).

Let's create the structural data first.

FlexMeasures offers a command to create a toy account with a battery:

.. code-block:: bash

    $ flexmeasures add toy-account --kind battery

    Generic asset type `solar` created successfully.
    Generic asset type `wind` created successfully.
    Generic asset type `one-way_evse` created successfully.
    Generic asset type `two-way_evse` created successfully.
    Generic asset type `battery` created successfully.
    Generic asset type `building` created successfully.
    Generic asset type `process` created successfully.
    Creating account Toy Account ...
    Toy account Toy Account with user toy-user@flexmeasures.io created successfully. You might want to run `flexmeasures show account --id 1`
    Adding transmission zone type ...
    Adding NL transmission zone ...
    Created day-ahead prices
    The sensor recording day-ahead prices is day-ahead prices (ID: 1).
    Created <GenericAsset None: 'toy-battery' (battery)>
    Created discharging
    Created <GenericAsset None: 'toy-solar' (solar)>
    Created production
    The sensor recording battery discharging is discharging (ID: 2).
    The sensor recording solar forecasts is production (ID: 3).



And with that, we're done with the structural data for this tutorial!

If you want, you can inspect what you created:

.. code-block:: bash

    $ flexmeasures show account --id 1

    ===========================
    Account Toy Account (ID: 1)
    ===========================

    Account has no roles.

    All users:
    
    ID  Name      Email                     Last Login    Last Seen    Roles
    ----  --------  ------------------------  ------------  -----------  -------------
    1  toy-user  toy-user@flexmeasures.io  None          None         account-admin

    All assets:
    
    ID  Name           Type     Location
    ----  -----------  -------  -----------------
    2  toy-building   building  (52.374, 4.88969)
    3  toy-battery    battery   (52.374, 4.88969)
    4  toy-solar      solar     (52.374, 4.88969)

.. code-block:: bash

    $ flexmeasures show asset --id 2

    =========================
    Asset toy-building (ID: 2)
    =========================

    Type      Location           Attributes
    -------   -----------------  ----------------------------
    building  (52.374, 4.88969)

    ====================================
    Child assets of toy-building (ID: 2)
    ====================================

    Id       Name               Type
    -------  -----------------  ----------------------------
    3        toy-battery        battery
    4        toy-solar          solar

    No sensors in asset ...

    $ flexmeasures show asset --id 3

    ==================================
    Asset toy-battery (ID: 3)
    Child of asset toy-building (ID: 2)
    ==================================

    Type     Location           Attributes
    -------  -----------------  ----------------------------
    battery  (52.374, 4.88969)  capacity_in_mw: 0.5
                                min_soc_in_mwh: 0.05
                                max_soc_in_mwh: 0.45
                                sensors_to_show: [1, [3, 2]]

    ====================================
    Child assets of toy-battery (ID: 3)
    ====================================

    No children assets ...

    All sensors in asset:
    
    ID  Name         Unit    Resolution    Timezone          Attributes
    ----  -----------  ------  ------------  ----------------  ------------
    2  discharging  MW      15 minutes    Europe/Amsterdam


Yes, that is quite a large battery :)

.. note:: Obviously, you can use the ``flexmeasures`` command to create your own, custom account and assets. See :ref:`cli`. And to create, edit or read asset data via the API, see :ref:`v3_0`.

We can also look at the battery asset in the UI of FlexMeasures (in Docker, the FlexMeasures web server already runs, on your PC you can start it with ``flexmeasures run``).
Visit `http://localhost:5000/ <http://localhost:5000/>`_ (username is "toy-user@flexmeasures.io", password is "toy-password"):

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/asset-view-dashboard.png
    :align: center
|

.. note:: You won't see the map tiles, as we have not configured the :ref:`MAPBOX_ACCESS_TOKEN`. If you have one, you can configure it via ``flexmeasures.cfg`` (for Docker, see :ref:`docker_configuration`).


.. _tut_toy_schedule_price_data:

Add some price data
---------------------------------------

Now to add price data. First, we'll create the CSV file with prices (EUR/MWh, see the setup for sensor 1 above) for tomorrow.

.. code-block:: bash

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

This is time series data, in FlexMeasures we call *"beliefs"*. Beliefs can also be sent to FlexMeasures via API or imported from open data hubs like `ENTSO-E <https://github.com/SeitaBV/flexmeasures-entsoe>`_ or `OpenWeatherMap <https://github.com/SeitaBV/flexmeasures-openweathermap>`_. However, in this tutorial we'll show how you can read data in from a CSV file. Sometimes that's just what you need :)

.. code-block:: bash

    $ flexmeasures add beliefs --sensor 1 --source toy-user prices-tomorrow.csv --timezone Europe/Amsterdam
    Successfully created beliefs

In FlexMeasures, all beliefs have a data source. Here, we use the username of the user we created earlier. We could also pass a user ID, or the name of a new data source we want to use for CLI scripts.

.. note:: Attention: We created and imported prices where the times have no time zone component! That happens a lot. FlexMeasures can localize them for you to a given timezone. Here, we localized the data to the timezone of the price sensor - ``Europe/Amsterdam`` - so the start time for the first price is `2022-03-03 00:00:00+01:00` (midnight in Amsterdam).

Let's look at the price data we just loaded:

.. code-block:: bash

    $ flexmeasures show beliefs --sensor 1 --start ${TOMORROW}T00:00:00+01:00 --duration PT24H
    
    Beliefs for Sensor 'day-ahead prices' (ID 1).
    Data spans a day and starts at 2022-03-03 00:00:00+01:00.
    The time resolution (x-axis) is an hour.
    ┌────────────────────────────────────────────────────────────┐
    │       ▗▀▚▖                                                 │
    │      ▗▘  ▝▖                                                │
    │      ▞    ▌                                                │
    │     ▟     ▐                                                │ 15EUR/MWh
    │    ▗▘     ▝▖                                      ▗        │
    │   ▗▘       ▚                                    ▄▞▘▚▖      │
    │   ▞        ▐                                  ▄▀▘   ▝▄     │
    │ ▄▞          ▌                                ▛        ▖    │
    │▀            ▚                               ▐         ▝▖   │
    │             ▝▚            ▖                ▗▘          ▝▖  │ 10EUR/MWh
    │               ▀▄▄▞▀▄▄   ▗▀▝▖               ▞            ▐  │
    │                      ▀▀▜▘  ▝▚             ▗▘             ▚ │
    │                              ▌            ▞               ▌│
    │                              ▝▖          ▞                ▝│
    │                               ▐         ▞                  │
    │                                ▚      ▗▞                   │ 5EUR/MWh
    │                                 ▀▚▄▄▄▄▘                    │
    └────────────────────────────────────────────────────────────┘
               5            10            15           20
                         ██ day-ahead prices



Again, we can also view these prices in the `FlexMeasures UI <http://localhost:5000/sensors/1>`_:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-prices.png
    :align: center
|

.. note:: Technically, these prices for tomorrow may be forecasts (depending on whether you are running through this tutorial before or after the day-ahead market's gate closure). You can also use FlexMeasures to compute forecasts yourself. See :ref:`tut_forecasting_scheduling`.


