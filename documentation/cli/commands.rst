.. _cli:

CLI Commands
=============================

FlexMeasures comes with a command-line utility, which helps to manage data.
Below, we list all available commands.

Each command has more extensive documentation if you call it with ``--help``.

We keep track of changes to these commands in :ref:`cli-changelog`.
You can also get the current overview over the commands you have available by:

.. code-block::

    flexmeasures --help

This also shows admin commands made available through Flask and installed extensions (such as `Flask-Security <https://flask-security-too.readthedocs.io>`_ and `Flask-Migrate <https://flask-migrate.readthedocs.io>`_),
of which some are referred to in this documentation.


``add`` - Add data
--------------

================================================= =======================================
``flexmeasures add structure``                    Initialize structural data like asset types, 
                                                  market types and weather sensor types.
``flexmeasures add account-role``                 Create a FlexMeasures tenant account role.
``flexmeasures add account``                      Create a FlexMeasures tenant account.
``flexmeasures add user``                         Create a FlexMeasures user.
``flexmeasures add asset-type``                   Create a new asset type.
``flexmeasures add asset``                        Create a new asset.
``flexmeasures add sensor``                       Add a new sensor.
``flexmeasures add weather-sensor``               Add a weather sensor.
``flexmeasures add external-weather-forecasts``   Collect weather forecasts from the DarkSky API.
``flexmeasures add beliefs``                      Load beliefs from file.
``flexmeasures add forecasts``                    Create forecasts.
================================================= =======================================


``show`` - Show data
--------------

================================================= =======================================
``flexmeasures show accounts``                    List accounts.
``flexmeasures show account``                     Show an account, its users and assets.
``flexmeasures show asset-types`                  List available asset types.
``flexmeasures show asset``                       Show an asset and its sensors.
``flexmeasures show roles``                       List available account- and user roles.
``flexmeasures show data-sources``                List available data sources.
================================================= =======================================


``delete`` - Delete data
--------------

================================================= =======================================
``flexmeasures delete structure``                 Delete all structural (non time-series) data like assets (types), 
                                                  markets (types) and weather sensors (types) and users.
``flexmeasures delete account-role``              Delete a tenant account role.
``flexmeasures delete account``                   Delete a tenant account & also their users (with assets and power measurements).
``flexmeasures delete user``                      Delete a user & also their assets and power measurements.
``flexmeasures delete sensor``                    Delete a sensor and all beliefs about it.
``flexmeasures delete measurements``              Delete measurements (with horizon <= 0).
``flexmeasures delete prognoses``                 Delete forecasts and schedules (forecasts > 0).
``flexmeasures delete unchanged-beliefs``         Delete unchanged beliefs.
``flexmeasures delete nan-beliefs``               Delete NaN beliefs.
================================================= =======================================


``jobs`` - Job queueing
--------------

================================================= =======================================
``flexmeasures jobs run-worker``                  Start a worker process for forecasting and/or scheduling jobs.
``flexmeasures jobs clear-queue``                 Clear a job queue.
================================================= =======================================


``db-ops`` - Operations on the whole database
--------------

================================================= =======================================
``flexmeasures db-ops dump``                      Create a dump of all current data (using `pg_dump`).
``flexmeasures db-ops load``                      Load backed-up contents (see `db-ops save`), run `reset` first.
``flexmeasures db-ops reset``                     Reset database data and re-create tables from data model.
``flexmeasures db-ops restore``                   Restore the dump file, see `db-ops dump` (run `reset` first).
``flexmeasures db-ops save``                      Backup db content to files.
================================================= =======================================
