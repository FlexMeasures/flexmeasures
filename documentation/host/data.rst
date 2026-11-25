.. _host-data:

Postgres database
=====================

This document describes how to get the postgres database ready to use and maintain it (do migrations / changes to the structure).

.. note:: This is about a stable database, useful for longer development work or production. A super quick way to get a postgres database running with Docker is described in :ref:`tut_toy_schedule`. In :ref:`docker-compose` we use both postgres and redis.

We also spend a few words on coding with database transactions in mind.


.. contents:: Table of contents
    :local:
    :depth: 2


Getting ready to use
----------------------

Notes: 

* We assume ``flexmeasures`` for your database and username here. You can use anything you like, of course.
* The name ``flexmeasures_test`` for the test database is good to keep this way, as automated tests are looking for that database / user / password. 

Install
^^^^^^^^^^^^^

We believe FlexMeasures works with Postgres above version 9 and we ourselves have run it with versions up to 17.

On Linux:

.. code-block:: bash

   $ # On Ubuntu and Debian, you can install postgres like this:
   $ sudo apt-get install postgresql-17  # replace 17 with the version available in your packages
   $ pip install "psycopg[binary]"

   $ # On Fedora, you can install postgres like this:
   $ sudo dnf install postgresql postgresql-server
   $ sudo postgresql-setup --initdb --unit postgresql


On Windows:


* Download postgres here: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads
* Install and remember your ``postgres`` user password
* Add the lib and bin directories to your Windows path: http://bobbyong.com/blog/installing-postgresql-on-windoes/
* ``conda install psycopg``


On Macos:

.. code-block:: bash

   $ brew update
   $ brew doctor
   $ # Need to specify postgres version, in this example we use 17
   $ brew install postgresql@17
   $ brew link postgresql@17 --force
   $ # Start postgres (you can change /usr/local/var/postgres to any directory you like)
   $ pg_ctl -D /usr/local/var/postgres -l logfile start


Using Docker Compose:


Alternatively, you can use Docker Compose to run a postgres database. You can use the following ``docker-compose.yml`` as a starting point:


.. code-block:: yaml

   version: '3.7'

   services:
     postgres:
       image: postgres:latest
       restart: always
       environment:
         POSTGRES_USER: flexmeasures
         POSTGRES_PASSWORD: this-is-your-secret-choice
         POSTGRES_DB: flexmeasures
       ports:
         - 5432:5432
       volumes:
         - ./postgres-data:/var/lib/postgresql/data
       network_mode: host

To run this, simply type ``docker-compose up`` in the directory where you saved the ``docker-compose.yml`` file. Pass the ``-d`` flag to run it in the background.

This will create a postgres database in a directory ``postgres-data`` in your current working directory. You can change the password and database name to your liking. You can also change the port mapping to e.g. ``5433:5432`` if you already have a postgres database running on your host machine.


Make sure postgres represents datetimes in UTC timezone
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

(Otherwise, pandas can get confused with daylight saving time.)

Luckily, many web hosts already have ``timezone= 'UTC'`` set correctly by default,
but local postgres installations often use ``timezone='localtime'``.

In any case, check both your local installation and the server, like this:

Find the ``postgres.conf`` file. Mine is at ``/etc/postgresql/9.6/main/postgresql.conf``.
You can also type ``SHOW config_file;`` in a postgres console session (as superuser) to find the config file.

Find the ``timezone`` setting and set it to 'UTC'.

Then restart the postgres server.

.. tabs::

   .. tab:: Linux

      .. code-block:: bash

         $ sudo service postgresql restart

   .. tab:: Macos

      .. code-block:: bash

         $ pg_ctl -D /usr/local/var/postgres -l logfile restart

.. note:: If you are using Docker to run postgres, the ``timezone`` setting is already set to ``UTC`` by default.


Create "flexmeasures" and "flexmeasures_test" databases and users
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

From the terminal:

Open a console (use your Windows key and type ``cmd``\ ).
Proceed to create a database as the postgres superuser (using your postgres user password):

.. code-block:: bash

   $ sudo -i -u postgres
   $ createdb -U postgres flexmeasures
   $ createdb -U postgres flexmeasures_test
   $ createuser --pwprompt -U postgres flexmeasures      # enter your password
   $ createuser --pwprompt -U postgres flexmeasures_test  # enter "flexmeasures_test" as password
   $ exit

.. note:: In case you encounter the following "FAILS: sudo: unknown user postgres" you need to create "postgres" OS user with sudo rights first - better done via System preferences -> Users & Groups.


Or, from within Postgres console:

.. code-block:: sql

   CREATE USER flexmeasures WITH PASSWORD 'this-is-your-secret-choice';
   CREATE DATABASE flexmeasures WITH OWNER = flexmeasures;
   CREATE USER flexmeasures_test WITH PASSWORD 'flexmeasures_test';
   CREATE DATABASE flexmeasures_test WITH OWNER = flexmeasures_test;


Finally, test if you can log in as the flexmeasures user:

.. code-block:: bash

   $ psql -U flexmeasures --password -h 127.0.0.1 -d flexmeasures

.. code-block:: psql

   \q


Add Postgres Extensions to your database(s)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To find the nearest sensors, FlexMeasures needs some extra Postgres support.
Add the following extensions while logged in as the postgres superuser:

.. code-block:: bash

   $ sudo -u postgres psql

.. code-block:: psql

   \connect flexmeasures
   CREATE EXTENSION cube;
   CREATE EXTENSION earthdistance;

.. note:: Lines from above should be run seperately


If you have it, connect to the ``flexmeasures_test`` database and repeat creating these extensions there. Then ``exit``.


Configure FlexMeasures app for that database
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Write:

.. code-block:: python

   SQLALCHEMY_DATABASE_URI = "postgresql://flexmeasures:<password>@127.0.0.1/flexmeasures"


into the config file you are using, e.g. ~/.flexmeasures.cfg


Get structure (and some data) into place
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You need data to enjoy the benefits of FlexMeasures or to develop features for it. In this section, there are some ways to get started.


Import from another database
""""""""""""""""""""""""""""""

Here is a short recipe to import data from a FlexMeasures database (e.g. a demo database) into your local system.

On the to-be-exported database:

.. code-block:: bash

   $ flexmeasures db-ops dump


.. note:: Only the data gets dumped here.

Then, we create the structure in our database anew, based on the data model given by the local codebase:

.. code-block:: bash

   $ flexmeasures db-ops reset


Then we import the data dump we made earlier:

.. code-block:: bash

   $ flexmeasures db-ops restore <DATABASE DUMP FILENAME>


A potential ``alembic_version`` error should not prevent other data tables from being restored.
You can also choose to import a complete db dump into a freshly created database, of course.

.. note:: To make sure passwords will be decrypted correctly when you authenticate, set the same SECURITY_PASSWORD_SALT value in your config as the one that was in use when the dumped passwords were encrypted! 

Create data manually
"""""""""""""""""""""""

First, you can get the database structure with:

.. code-block:: bash

   $ flexmeasures db upgrade


.. note:: If you develop code (and might want to make changes to the data model), you should also check out the maintenance section about database migrations.


You should create some pre-determined asset types, user/account roles and data sources with this command:

.. code-block:: bash

   $ flexmeasures add initial-structure


Another good first step is to create an account for yourself, plus a user to log in with:

.. code-block:: bash

   $ flexmeasures add account --help
   $ flexmeasures add user --help

Creating accounts and users for your clients would also happen this way (soon also in the UI). 

You can also create assets in the CLI (``flexmeasures add asset``), but that is also possible in the FlexMeasures UI.

Actually, you can add many things from the terminal. Check what data you can add yourself:

.. code-block:: bash

   $ flexmeasures add --help


For instance, you can create forecasts for your existing metered data with this command:

.. code-block:: bash

   $ flexmeasures add forecasts --help


Check out it's ``--help`` content to learn more. You can set which assets and which time window you want to forecast. Of course, making forecasts takes a while for a larger dataset.
You can also simply queue a job with this command (and run a worker to process the :ref:`redis-queue`).

Just to note, there are also commands to get rid of data. Check:

.. code-block:: bash

   $ flexmeasures delete --help

Check out the :ref:`cli` documentation for more details.


.. _host-data-timescaledb:

Optional: store time series data with TimescaleDB
--------------------------------------------------

FlexMeasures keeps all time series data in one table, ``timed_belief``.
If your PostgreSQL server provides the `TimescaleDB <https://docs.timescale.com>`_ extension (version 2.13 or later),
you can turn that table into a TimescaleDB *hypertable*:
the same table to FlexMeasures, but stored in chunks by event time,
of which the older ones can be compressed.
FlexMeasures does not need this, and its queries do not change.

.. code-block:: bash

   $ flexmeasures db-ops enable-timescaledb --chunk-time-interval "7 days" --compress-after "30 days"

What to expect:

- **Much less storage.** Compressed chunks, segmented per sensor and data source, typically take an order of magnitude less space, indexes included.
  In a test with 7 million beliefs, the table and its indexes went from 1.6 GB to 115 MB.
  Smaller data means more of it stays in memory, which matters most once your data no longer fits in RAM.
- **Similar query times while data fits in memory.** Most queries ask for one sensor and a time range, which the primary key already serves well, so on a database that fits in memory, expect little difference either way.
- **Slower queries without a time range.** A query that does not bound event time, such as asking for the most recent value of a sensor, is planned against every chunk, which adds milliseconds per query on a table with many chunks. Larger chunks reduce this.
- **Slower writes to compressed data.** Compressed chunks still accept new and updated beliefs, but pick a ``--compress-after`` beyond which data is rarely rewritten.

Before you run it:

- Converting moves all existing beliefs into chunks, and blocks writes to the table until it is done (in our test, 34 seconds for 7 million beliefs). Plan a maintenance window for a large database.
- There is no command to go back to a plain table: that takes a dump and restore of the time series data.
- Some database migrations (in FlexMeasures or in your plugins) may build indexes ``CONCURRENTLY``, which TimescaleDB does not support on hypertables. We will keep this in mind, but check before upgrading.
- Not all managed PostgreSQL services offer TimescaleDB, and some only offer its Apache-licensed edition, which has no compression.
- TimescaleDB sends anonymous usage data by default. To turn that off, set ``timescaledb.telemetry_level = off`` in your ``postgresql.conf``.

Run the command again to add or change compression on a table that is already a hypertable.


Visualize the data model
--------------------------

You can visualise the data model like this:

.. code-block:: bash

   $ uv run poe show-data-model --uml


This will generate a picture based on the model code.
You can also generate picture based on the actual database with ``uv run poe show-data-model --schema``.

Maintenance
----------------

Maintenance is supported with the alembic tool. It reacts automatically
to almost all changes in the SQLAlchemy code. With alembic, multiple databases,
such as development, staging and production databases can be kept in sync.


Make first migration
^^^^^^^^^^^^^^^^^^^^^^^

Run these commands from the repository root directory (read below comments first):

.. code-block:: bash

   $ flexmeasures db init
   $ flexmeasures db migrate
   $ flexmeasures db upgrade


The first command (\ ``flexmeasures db init``\ ) is only needed here once, it initialises the alembic migration tool.
The second command generates the SQL for your current db model and the third actually gives you the db structure.

With every migration, you get a new migration step in ``migrations/versions``. Be sure to add that to ``git``\ ,
as future calls to ``flexmeasures db upgrade`` will need those steps, and they might happen on another computer.

Hint: You can edit these migrations steps, if you want.

Make another migration
^^^^^^^^^^^^^^^^^^^^^^^

Just to be clear that the ``db init`` command is needed only at the beginning - you usually do, if your model changed:

.. code-block:: bash

   $ flexmeasures db migrate --message "Please explain what you did, it helps for later"
   $ flexmeasures db upgrade


Get database structure updated
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The goal is that on any other computer, you can always execute

.. code-block:: bash

   $ flexmeasures db upgrade


to have the database structure up-to-date with all migrations.

Working with the migration history
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The history of migrations is at your fingertips:

.. code-block:: bash

   $ flexmeasures db current
   $ flexmeasures db history


You can move back and forth through the history:

.. code-block:: bash

   $ flexmeasures db downgrade
   $ flexmeasures db upgrade


Both of these accept a specific revision id parameter, as well.

Check out database status
^^^^^^^^^^^^^^^^^^^^^^^^^

Log in into the database:

.. code-block:: bash

   $ psql -U flexmeasures --password -h 127.0.0.1 -d flexmeasures


with the password from flexmeasures/development_config.py. Check which tables are there:

.. code-block:: psql

   \dt


To log out:

.. code-block:: psql

   \q


Transaction management
-----------------------

It is really useful (and therefore an industry standard) to bundle certain database actions within a transaction. Transactions are atomic - either the actions in them all run or the transaction gets rolled back. This keeps the database in a sane state and really helps having expectations during debugging.

Please see the package ``flexmeasures.data.transactional`` for details on how a FlexMeasures developer should make use of this concept.
If you are writing a script or a view, you will find there the necessary structural help to bundle your work in a transaction.
