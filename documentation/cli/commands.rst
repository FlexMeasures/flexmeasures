.. _cli:

Command Line Interface (CLI)
=============================

FlexMeasures comes with a command-line utility, which helps to to manage data.
Below, we list all available commands.

Each command has more extensive documentation if you call it with ``--help``.

We keep track of changes to these commands in :ref:`cli-changelog`.
You can also get the current overview over the commands yiu have available by:

.. code-block::

    flexmeasures --help

This will also show commands made available through Flask and the installed extensions (e.g. `Flask-Security <https://flask-security-too.readthedocs.io>`_, or `Flask-Migrate <https://flask-migrate.readthedocs.io>`_). These are also very interesting for admins (and partially come up in this documentation).


``add`` : Add data
--------------

================================================= =======================================
``flexmeasures add structure``                    Initialize the database with static values.
``flexmeasures add user``                         Create a FlexMeasures user.
``flexmeasures add asset``                        Create a new asset.
``flexmeasures add weather-sensor``               Add a weather sensor.
``flexmeasures add external-weather-forecasts``   Collect weather forecasts from the DarkSky API.
``flexmeasures add forecasts``                    Create forecasts.
================================================= =======================================


``delete`` : Delete data
--------------

================================================= =======================================
``flexmeasures delete structure``                 Delete structural data like asset (types), 
                                                  market (types), weather (sensors), users, roles.
``flexmeasures delete user``                      Delete a user & also their data.
``flexmeasures delete measurements``              Delete measurements (with horizon <= 0).
``flexmeasures delete prognoses``                 Delete forecasts and schedules (forecasts > 0).
================================================= =======================================


``jobs`` : Job queueing
--------------

================================================= =======================================
``flexmeasures jobs run-worker``                  Start a worker process for forecasting and/or scheduling jobs.
``flexmeasures jobs clear-queue``                 Clear a job queue.
================================================= =======================================


``db-ops`` : Operations on the whole database
--------------

================================================= =======================================
``flexmeasures db-ops dump``                      Create a database dump of the database used by the app.
``flexmeasures db-ops load``                      Load structure and/or data for the database from a backup file.
``flexmeasures db-ops reset``                     Reset database, with options to load fresh data.
``flexmeasures db-ops restore``                   Restore the database used by the app, from a given database 
                                                  dump file, after you've reset the database.
``flexmeasures db-ops save``                      Save structure of the database to a backup file.
================================================= =======================================