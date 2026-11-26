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
If your PostgreSQL server provides the `TimescaleDB <https://docs.timescale.com>`_ extension (version 2.18 or later),
you can turn that table into a compressed TimescaleDB *hypertable*:
the same table to FlexMeasures, but stored in chunks by event time,
of which the ones with events older than a given age are compressed.
FlexMeasures does not need this, and its queries do not change.
(Version 2.18 is the first whose hypertables support the trigger FlexMeasures keeps on ``timed_belief``,
which records which data sources have data on which sensors.)

.. code-block:: bash

   $ flexmeasures db-ops enable-timescaledb --chunk-time-interval "30 days" --compress-after "30 days"

Both options default to 30 days.

This suits live hosts with a long history, where storage is the concern.
It does not suit play servers (``FLEXMEASURES_MODE = "play"``),
whose simulations write into past periods and rerun over them,
which is the slow case of compressed data (see below).
The command refuses to run on a play server, unless you add ``--force``.

What to expect
^^^^^^^^^^^^^^

Compression is about storage, not speed.
Measured on 2.24 million beliefs on an SSD, with the table three times larger than the database server's memory:

- **Storage about 8 times smaller**: the table and its indexes went from 533 MiB to 63 MiB.
- **Reads are mixed**: a week of forecasts (most recent beliefs) came back 2 times faster, but one meter's day 4 times slower, and the latest value of a sensor (a query without a time range, which is planned against every chunk) 3.6 times slower. Larger chunks reduce the latter.
- **Writes into compressed periods are slower**: late data took 1.2 times as long, and overwriting beliefs (upserts) 2.6 times as long. Deleting beliefs there costs a decompression, too. Pick a ``--compress-after`` beyond which data is rarely rewritten.
- **Converting takes minutes for a large host**: 94 seconds for 2.24 million beliefs on 2 CPUs, then 14 seconds of compression.

A hypertable without compression was slower than the plain table on every read and no smaller,
so the command always compresses,
and refuses to run on TimescaleDB's Apache-licensed edition (offered by some managed services), which cannot compress.

Before you run it
^^^^^^^^^^^^^^^^^

- Converting moves all existing beliefs into chunks, and blocks writes to the table until it is done. Plan a maintenance window for a large database.
- Backups of a converted database need TimescaleDB's own procedure: a full dump, restored with ``timescaledb_pre_restore()`` and ``timescaledb_post_restore()`` into a database with the same TimescaleDB version. A data-only dump (as made by ``flexmeasures db-ops dump``) holds the beliefs in TimescaleDB's chunk tables, so restoring it into a plain database brings back none of them.
- TimescaleDB does not build or drop indexes ``CONCURRENTLY`` on hypertables, which some migrations do to let writes go on meanwhile. FlexMeasures' own migrations on ``timed_belief`` (``d4a7c1e93b52`` and ``b7e5a2c40f18``) leave it out on a hypertable, and so should migrations in plugins that change indexes on ``timed_belief``: ``flexmeasures.data.migration_utils`` has helpers for that.
- If you later move a compressed database to a server with the Apache-licensed edition, its compressed chunks can still be read, but writing into them fails.
- TimescaleDB sends anonymous usage data by default. To turn that off, set ``timescaledb.telemetry_level = off`` in your ``postgresql.conf``. The command warns while it is on.

Changing the settings later
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Run the command again on the hypertable:
``--compress-after`` replaces the age after which chunks are compressed (and compresses the chunks that qualify now),
and ``--chunk-time-interval`` sets how much event time new chunks span (existing chunks keep theirs).

Going back to a plain table
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   $ flexmeasures db-ops disable-timescaledb

This copies all beliefs into a new plain ``timed_belief`` table, decompressing them on the way,
gives it its primary key, indexes, foreign keys and trigger,
and drops the hypertable.
Reads and writes of time series data wait until it is done.
The database needs room for the decompressed beliefs and their indexes next to the hypertable, which the command estimates before it asks to continue.
The new table is owned by the database user FlexMeasures runs as, so privileges granted on the hypertable to other users need to be granted again.
The database needs to be migrated to the latest revision first (``flexmeasures db upgrade``), as the plain table is created from the current data model.


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
