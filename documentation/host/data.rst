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

* We use postgres 12 at the moment, but any version starting with 9 probably works.
* We assume ``flexmeasures`` for your database and username here. You can use anything you like, of course.
* The name ``flexmeasures_test`` for the test database is good to keep this way, as automated tests are looking for that database / user / password. 

Install
^^^^^^^^^^^^^

On Unix:

.. code-block:: console

   sudo apt-get install postgresql-12
   pip install psycopg2-binary


On Windows:


* Download postgres here: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads
* Install and remember your ``postgres`` user password
* Add the lib and bin directories to your Windows path: http://bobbyong.com/blog/installing-postgresql-on-windoes/
* ``conda install psycopg2``


Make sure postgres represents datetimes in UTC timezone
^^^^^^^^^^^^^

(Otherwise, pandas can get confused with daylight saving time.)

Luckily, many web hosters already have ``timezone= 'UTC'`` set correctly by default,
but local postgres installations often use ``timezone='localtime'``.

In any case, check both your local installation and the server, like this:

Find the ``postgres.conf`` file. Mine is at ``/etc/postgresql/9.6/main/postgresql.conf``.
You can also type ``SHOW config_file;`` in a postgres console session (as superuser) to find the config file.

Find the ``timezone`` setting and set it to 'UTC'.

Then restart the postgres server.

.. code-block:: console

    service postgresql restart


Setup the "flexmeasures" Unix user
^^^^^^^^^^^^^

This may in fact not be needed:

.. code-block:: console

   sudo /usr/sbin/adduser flexmeasures


Create "flexmeasures" and "flexmeasures_test" databases and users
^^^^^^^^^^^^^

From the terminal:

Open a console (use your Windows key and type ``cmd``\ ).
Proceed to create a database as the postgres superuser (using your postgres user password):

.. code-block:: console

   sudo -i -u postgres
   createdb -U postgres flexmeasures
   createdb -U postgres flexmeasures_test
   createuser --pwprompt -U postgres flexmeasures      # enter your password
   createuser --pwprompt -U postgres flexmeasures_test  # enter "flexmeasures_test" as password
   exit


Or, from within Postgres console:

.. code-block:: sql

   CREATE USER flexmeasures WITH UNENCRYPTED PASSWORD 'this-is-your-secret-choice';
   CREATE DATABASE flexmeasures WITH OWNER = flexmeasures;
   CREATE USER flexmeasures_test WITH UNENCRYPTED PASSWORD 'flexmeasures_test';
   CREATE DATABASE flexmeasures_test WITH OWNER = flexmeasures_test;


Finally, test if you can log in as the flexmeasures user:

.. code-block:: console

   psql -U flexmeasures --password -h 127.0.0.1 -d flexmeasures

.. code-block:: sql

   \q


Add Postgres Extensions to your database(s)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To find the nearest sensors, FlexMeasures needs some extra Postgres support.
Add the following extensions while logged in as the postgres superuser:

.. code-block:: console

   sudo -u postgres psql

.. code-block:: sql

   \connect flexmeasures
   CREATE EXTENSION cube;
   CREATE EXTENSION earthdistance;


If you have it, connect to the ``flexmeasures_test`` database and repeat creating these extensions there. Then ``exit``.


Configure FlexMeasures app for that database
^^^^^^^^^^^^^

Write:

.. code-block:: python

   SQLALCHEMY_DATABASE_URI = "postgresql://flexmeasures:<password>@127.0.0.1/flexmeasures"


into the config file you are using, e.g. ~/flexmeasures.cfg


Get structure (and some data) into place
^^^^^^^^^^^^^

You need data to enjoy the benefits of FlexMeasures or to develop features for it. In this section, there are some ways to get started.


Import from another database
""""""""""""""""""""""""""""""

Here is a short recipe to import data from a FlexMeasures database (e.g. a demo database) into your local system.

On the to-be-exported database:

.. code-block:: console

   flexmeasures db-ops dump


.. note:: Only the data gets dumped here.

Then, we create the structure in our database anew, based on the data model given by the local codebase:

.. code-block:: console

   flexmeasures db-ops reset


Then we import the data dump we made earlier:

.. code-block:: console

   flexmeasures db-ops restore <DATABASE DUMP FILENAME>


A potential ``alembic_version`` error should not prevent other data tables from being restored.
You can also choose to import a complete db dump into a freshly created database, of course.

.. note:: To make sure passwords will be decrypted correctly when you authenticate, set the same SECURITY_PASSWORD_SALT value in your config as the one that was in use when the dumped passwords were encrypted! 

Create data manually
"""""""""""""""""""""""

First, you can get the database structure with:

.. code-block:: console

   flexmeasures db upgrade


.. note:: If you develop code (and might want to make changes to the data model), you should also check out the maintenance section about database migrations.

You can create users with the ``new-user`` command. Check it out:

.. code-block:: console

   flexmeasures add user --help


You can create some pre-determined asset types and data sources with this command:

.. code-block:: console

   flexmeasures add initial-structure

You can also create assets in the FlexMeasures UI.

On the command line, you can add many things. Check what data you can add yourself:

.. code-block:: console

   flexmeasures add --help


For instance, you can create forecasts for your existing metered data with this command:

.. code-block:: console

   flexmeasures add forecasts --help


Check out it's ``--help`` content to learn more. You can set which assets and which time window you want to forecast. Of course, making forecasts takes a while for a larger dataset.
You can also simply queue a job with this command (and run a worker to process the :ref:`redis-queue`).

Just to note, there are also commands to get rid of data. Check:

.. code-block:: console

   flexmeasures delete --help

Check out the :ref:`cli` documentation for more details.



Visualize the data model
--------------------------

You can visualise the data model like this:

.. code-block:: console

   make show-data-model


This will generate a picture based on the model code.
You can also generate picture based on the actual database, see inside the Makefile. 

Maintenance
----------------

Maintenance is supported with the alembic tool. It reacts automatically
to almost all changes in the SQLAlchemy code. With alembic, multiple databases,
such as development, staging and production databases can be kept in sync.


Make first migration
^^^^^^^^^^^^^^^^^^^^^^^

Run these commands from the repository root directory (read below comments first):

.. code-block:: console

   flexmeasures db init
   flexmeasures db migrate
   flexmeasures db upgrade


The first command (\ ``flexmeasures db init``\ ) is only needed here once, it initialises the alembic migration tool.
The second command generates the SQL for your current db model and the third actually gives you the db structure.

With every migration, you get a new migration step in ``migrations/versions``. Be sure to add that to ``git``\ ,
as future calls to ``flexmeasures db upgrade`` will need those steps, and they might happen on another computer.

Hint: You can edit these migrations steps, if you want.

Make another migration
^^^^^^^^^^^^^^^^^^^^^^^

Just to be clear that the ``db init`` command is needed only at the beginning - you usually do, if your model changed:

.. code-block:: console

   flexmeasures db migrate --message "Please explain what you did, it helps for later"
   flexmeasures db upgrade


Get database structure updated
^^^^^^^^^^^^^^^^^^^^^^^

The goal is that on any other computer, you can always execute

.. code-block:: console

   flexmeasures db upgrade


to have the database structure up-to-date with all migrations.

Working with the migration history
^^^^^^^^^^^^^^^^^^^^^^^

The history of migrations is at your fingertips:

.. code-block:: console

   flexmeasures db current
   flexmeasures db history


You can move back and forth through the history:

.. code-block:: console

   flexmeasures db downgrade
   flexmeasures db upgrade


Both of these accept a specific revision id parameter, as well.

Check out database status
^^^^^^^^^^^^^^^^^^^^^^^

Log in into the database:

.. code-block:: console

   psql -U flexmeasures --password -h 127.0.0.1 -d flexmeasures


with the password from flexmeasures/development_config.py. Check which tables are there:

.. code-block:: sql

   \dt


To log out:

.. code-block:: sql

   \q


Transaction management
-----------------------

It is really useful (and therefore an industry standard) to bundle certain database actions within a transaction. Transactions are atomic - either the actions in them all run or the transaction gets rolled back. This keeps the database in a sane state and really helps having expectations during debugging.

Please see the package ``flexmeasures.data.transactional`` for details on how a FlexMeasures developer should make use of this concept.
If you are writing a script or a view, you will find there the necessary structural help to bundle your work in a transaction.
