.. _docker-compose:

Running a complete stack with docker-compose
=============================================

To install FlexMeasures, plus the libraries and databases it depends on, on your computer is some work, and can have unexpected hurdles, e.g. depending on the operating system. A nice alternative is to let that happen within Docker. The whole stack can be run via `Docker compose <https://docs.docker.com/compose/>`_, saving the developer much time.

For this, we assume you are in the directory (in the `FlexMeasures git repository <https://github.com/FlexMeasures/flexmeasures>`_) housing ``docker-compose.yml``.


.. note:: The minimum Docker version is 17.09 and for docker-compose we tested successfully at version 1.25. You can check your versions with ``docker[-compose] --version``.

.. note:: The command might also be ``docker compose`` (no dash), for instance if you are using `Docker Desktop <https://docs.docker.com/desktop>`_.

Build the compose stack
------------------------

Run this:

.. code-block:: bash

    $ docker-compose build

This pulls the images you need, and re-builds the FlexMeasures ones from code. If you change code, re-running this will re-build that image.

This compose script can also serve as an inspiration for using FlexMeasures in modern cloud environments (like Kubernetes). For instance, you might want to not build the FlexMeasures image from code, but simply pull the image from DockerHub.

If you wanted, you could stop building from source, and directly use the official flexmeasures image for the server and worker container
(set ``image: lfenergy/flexmeasures`` in the file ``docker-compose.yml``).


Run the compose stack
----------------------

Start the stack like this:

.. code-block:: bash

    $ docker-compose up

.. warning:: This might fail if ports 5000 (Flask) or 6379 (Redis) are in use on your system. Stop these processes before you continue.

Check ``docker ps`` or ``docker-compose ps`` to see if your containers are running:


.. code-block:: bash

    $ docker ps
    CONTAINER ID   IMAGE                 COMMAND                  CREATED          STATUS                             PORTS                                            NAMES
    beb9bf567303   flexmeasures_server   "bash -c 'flexmeasur…"   44 seconds ago   Up 38 seconds (health: starting)   0.0.0.0:5000->5000/tcp                           flexmeasures-server-1
    e36cd54a7fd5   flexmeasures_worker   "flexmeasures jobs r…"   44 seconds ago   Up 5 seconds                       5000/tcp                                         flexmeasures-worker-1
    c9985de27f68   postgres              "docker-entrypoint.s…"   45 seconds ago   Up 40 seconds                      5432/tcp                                         flexmeasures-test-db-1
    03582d37230e   postgres              "docker-entrypoint.s…"   45 seconds ago   Up 40 seconds                      5432/tcp                                         flexmeasures-dev-db-1
    25024ada1590   mailhog/mailhog       "MailHog"                45 seconds ago   Up 40 seconds                      0.0.0.0:1025->1025/tcp, 0.0.0.0:8025->8025/tcp   flexmeasures-mailhog-1
    792ec3d86e71   redis                 "docker-entrypoint.s…"   45 seconds ago   Up 40 seconds                      0.0.0.0:6379->6379/tcp                           flexmeasures-queue-db-1


The FlexMeasures server container has a health check implemented, which is reflected in this output and you can see which ports are available on your machine to interact.

You can use the terminal or ``docker-compose logs`` to look at output. ``docker inspect <container>`` and ``docker exec -it <container> bash`` can be quite useful to dive into details. 
We'll see the latter more in this tutorial.


Configuration
---------------

You can pass in your own configuration (e.g. for MapBox access token, or db URI, see below) like we described in :ref:`docker_configuration` ― put a file ``flexmeasures.cfg`` into a local folder called ``flexmeasures-instance`` (the volume should be already mapped).

In case your configuration loads FlexMeasures plugins that have additional dependencies, you can add a requirements.txt file to the same local folder. The dependencies listed in that file will be freshly installed each time you run ``docker-compose up``.


Data
-------

The postgres database is a test database with toy data filled in when the flexmeasures container starts.
You could also connect it to some other database (on your PC, in the cloud), by setting a different ``SQLALCHEMY_DATABASE_URI`` in the config. 


.. _docker-compose-tutorial:

Seeing it work: Running the toy tutorial
--------------------------------------

A good way to see if these containers work well together, and maybe to inspire how to use them for your own purposes, is the :ref:`tut_toy_schedule`.

The `flexmeasures-server` container already creates the toy account when it starts (see its initial command). We'll now walk through the rest of the toy tutorial, with one twist at the end, when we create the battery schedule.

Let's go into the `flexmeasures-worker` container:

.. code-block:: bash

    $ docker exec -it flexmeasures-worker-1 bash

There, we'll now add the price data, as described in :ref:`tut_toy_schedule_price_data`. Copy the commands from that section and run them in the container's bash session, to create the prices and add them to the FlexMeasures DB.

Next, we put a scheduling job in the worker's queue. This only works because we have the Redis container running ― the toy tutorial doesn't have it. The difference is that we're adding ``--as-job``:

.. code-block:: bash

    $ flexmeasures add schedule for-storage --sensor 2 --consumption-price-sensor 1 \
        --start ${TOMORROW}T07:00+01:00 --duration PT12H --soc-at-start 50% \
        --roundtrip-efficiency 90% --as-job

We should now see in the output of ``docker logs flexmeasures-worker-1`` something like the following:

.. code-block:: bash

    Running Scheduling Job d3e10f6d-31d2-46c6-8308-01ede48f8fdd: discharging, from 2022-07-06 07:00:00+01:00 to 2022-07-06 19:00:00+01:00

So the job had been queued in Redis, was then picked up by the worker process, and the result should be in our SQL database container. Let's check!

We'll not go into the server container this time, but simply send a command:

.. code-block:: bash

    $ TOMORROW=$(date --date="next day" '+%Y-%m-%d')
    $ docker exec -it flexmeasures-server-1 bash -c "flexmeasures show beliefs --sensor 2 --start ${TOMORROW}T07:00:00+01:00 --duration PT12H"

The charging/discharging schedule should be there:

.. code-block:: bash

    ┌────────────────────────────────────────────────────────────┐
    │   ▐            ▐▀▀▌                                     ▛▀▀│ 0.5MW
    │   ▞▌           ▌  ▌                                     ▌  │
    │   ▌▌           ▌  ▐                                    ▗▘  │
    │   ▌▌           ▌  ▐                                    ▐   │
    │  ▐ ▐          ▐   ▐                                    ▐   │
    │  ▐ ▐          ▐   ▝▖                                   ▞   │
    │  ▌ ▐          ▐    ▌                                   ▌   │
    │ ▐  ▝▖         ▌    ▌                                   ▌   │
    │▀▘───▀▀▀▀▖─────▌────▀▀▀▀▀▀▀▀▀▌─────▐▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▘───│ 0.0MW
    │         ▌    ▐              ▚     ▌                        │
    │         ▌    ▞              ▐    ▗▘                        │
    │         ▌    ▌              ▐    ▞                         │
    │         ▐   ▐               ▝▖   ▌                         │
    │         ▐   ▐                ▌  ▗▘                         │
    │         ▐   ▌                ▌  ▐                          │
    │         ▝▖  ▌                ▌  ▞                          │
    │          ▙▄▟                 ▐▄▄▌                          │ -0.5MW
    └────────────────────────────────────────────────────────────┘
               10           20           30          40
                            ██ discharging

Like in the original toy tutorial, we can also check in the server container's `web UI <http://localhost:5000/sensors/1/>`_ (username is "toy-user@flexmeasures.io", password is "toy-password"):

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/sensor-data-charging.png
    :align: center


Email Testing
----------------------------------

To test email functionality, MailHog is included in the Docker Compose stack. You can view the emails sent by the application by navigating to http://localhost:8025/ in your browser.

To verify this setup, try changing a user's password in the application. This action will trigger an email, which you can then view in `MailHog <http://localhost:8025/>`_.


Scripting with the Docker stack
----------------------------------

A very important aspect of this stack is if it can be put to interesting use.
For this, developers need to be able to script things ― like we just did with the toy tutorial.

Note that instead of starting a console in the containers, we can also send commands to them right away.
For instance, we sent the complete ``flexmeasures show beliefs`` command and then viewed the output on our own machine.
Likewise, we send the ``pytest`` command to run the unit tests (see below).

Used this way, and in combination with the powerful list of :ref:`cli`, this FlexMeasures Docker stack is scriptable for interesting applications and simulations!


Running tests
---------------

You can run tests in the flexmeasures docker container, using the database service ``test-db`` in the compose file (per default, we are using the ``dev-db`` database service).

After you've started the compose stack with ``docker-compose up``, run:

.. code-block:: bash

    $ docker exec -it -e SQLALCHEMY_TEST_DATABASE_URI="postgresql://fm-test-db-user:fm-test-db-pass@test-db:5432/fm-test-db" flexmeasures-server-1 pytest

This rounds up the developer experience offered by running FlexMeasures in Docker. Now you can develop FlexMeasures and also run your tests. If you develop plugins, you could extend the command being used, e.g. ``bash -c "cd /path/to/my/plugin && pytest"``. 