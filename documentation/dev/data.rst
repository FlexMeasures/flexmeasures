.. _dev-data:

Handling data
=============================

This document describes how to get the postgres database ready to use and maintain it (do migrations / changes to the structure).

We also spend a few words on coding with database transactions in mind.

Finally, we'll discuss how FlexMeasures is using Redis and redis-queues. When setting up on Windows, a guide to install the Redis-based queuing system for handling (forecasting) jobs.


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

.. code-block:: bash

   sudo apt-get install postgresql
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

.. code-block:: bash

    service postgresql restart


Setup the "flexmeasures" Unix user
^^^^^^^^^^^^^

This may in fact not be needed:

.. code-block:: bash

   sudo /usr/sbin/adduser flexmeasures


Create "flexmeasures" and "flexmeasures_test" databases and users
^^^^^^^^^^^^^

From the terminal:

Open a console (use your Windows key and type ``cmd``\ ).
Proceed to create a database as the postgres superuser (using your postgres user password):

.. code-block:: bash

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

.. code-block:: bash

   psql -U flexmeasures --password -h 127.0.0.1 -d flexmeasures

.. code-block:: sql

   \q


Add Postgres Extensions to your database(s)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To find the nearest sensors, FlexMeasures needs some extra POstgres support. 
Add the following extensions while logged in as the postgres superuser:

.. code-block:: bash

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

.. code-block:: bash

   flexmeasures db-ops dump


.. note:: Only the data gets dumped here.

Then, we create the structure in our database anew, based on the data model given by the local codebase:

.. code-block:: bash

   flexmeasures db-ops reset


Then we import the data dump we made earlier:

.. code-block:: bash

   flexmeasures db-ops restore <DATABASE DUMP FILENAME>


A potential ``alembic_version`` error should not prevent other data tables from being restored.
You can also choose to import a complete db dump into a freshly created database, of course.

.. note:: To make sure passwords will be decrypted correctly when you authenticate, set the same SECURITY_PASSWORD_SALT value in your config as the one that was in use when the dumped passwords were encrypted! 

Create data manually
"""""""""""""""""""""""

First, you can get the database structure with:

.. code-block:: bash

   flexmeasures db upgrade


.. note:: If you develop code (and might want to make changes to the data model), you should also check out the maintenance section about database migrations.

You can create users with the ``new-user`` command. Check it out:

.. code-block:: bash

   flexmeasures add user --help


You can create some pre-determined asset types and data sources with this command:

.. code-block:: bash

   flexmeasures add structure


.. todo:: We should instead offer CLI commands to be able to create asset types as needed.

You can create assets in the FlexMeasures UI.

.. todo:: Maybe a CLI command would help to script all data creation.
.. todo:: We still need a decent way to load in metering data, e.g. from CSV - often, a custom loading script will be necessary anyways.

You can create forecasts for your existing metered data with this command:

.. code-block:: bash

   flexmeasures add forecasts


Check out it's ``--help`` content to learn more. You can set which assets and which time window you want to forecast. Of course, making forecasts takes a while for a larger dataset.
You can also simply queue a job with this command (and run a worker to process the :ref:`redis-queue`).

Just to note, there are also commands to get rid of data, such as:

.. code-block:: bash

   flexmeasures delete structure
   flexmeasures delete measurements
   flexmeasures delete forecasts

Check out the :ref:`cli` documentation for more details.



Visualize the data model
--------------------------

You can visualise the data model like this:

.. code-block:: bash

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

.. code-block:: bash

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

.. code-block:: bash

   flexmeasures db migrate --message "Please explain what you did, it helps for later"
   flexmeasures db upgrade


Get database structure updated
^^^^^^^^^^^^^^^^^^^^^^^

The goal is that on any other computer, you can always execute

.. code-block:: bash

   flexmeasures db upgrade


to have the database structure up-to-date with all migrations.

Working with the migration history
^^^^^^^^^^^^^^^^^^^^^^^

The history of migrations is at your fingertips:

.. code-block:: bash

   flexmeasures db current
   flexmeasures db history


You can move back and forth through the history:

.. code-block:: bash

   flexmeasures db downgrade
   flexmeasures db upgrade


Both of these accept a specific revision id parameter, as well.

Check out database status
^^^^^^^^^^^^^^^^^^^^^^^

Log in into the database:

.. code-block:: bash

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


.. _redis-queue:

Redis queue
-----------------------

FlexMeasures supports jobs (e.g. forecasting) running asynchronously to the main FlexMeasures application using `Redis Queue <http://python-rq.org/>`_.

It relies on a Redis server, which is has to be installed locally, or used on a separate host. In the latter case, configure :ref:`redis-config` details in your FlexMeasures config file.

Forecasting jobs are usually created (and enqueued) when new data comes in via the API. To asynchronously work on these forecasting jobs, run this in a console:

.. code-block:: bash

   flexmeasures jobs run_worker --queue forecasting


You should be able to run multiple workers in parallel, if necessary. You can add the ``--name`` argument to keep them a bit more organized.

The FlexMeasures unit tests use fakeredis to simulate this task queueing, with no configuration required.


Inspect the queue and jobs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The first option to inspect the state of the ``forecasting`` queue should be via the formidable `RQ dashboard <https://github.com/Parallels/rq-dashboard>`_. If you have admin rights, you can access it at ``your-flexmeasures-url/rq/``\ , so for instance ``http://localhost:5000/rq/``. You can also start RQ dashboard yourself (but you need to know the redis server credentials):

.. code-block:: bash

   pip install rq-dashboard
   rq-dashboard --redis-host my.ip.addr.ess --redis-password secret --redis-database 0


RQ dashboard shows you ongoing and failed jobs, and you can see the error messages of the latter, which is very useful.

Finally, you can also inspect the queue and jobs via a console (\ `see the nice RQ documentation <http://python-rq.org/docs/>`_\ ), which is more powerful. Here is an example of inspecting the finished jobs and their results:

.. code-block:: python

   from redis import Redis
   from rq import Queue
   from rq.job import Job
   from rq.registry import FinishedJobRegistry

   r = Redis("my.ip.addr.ess", port=6379, password="secret", db=2)
   q = Queue("forecasting", connection=r)
   finished = FinishedJobRegistry(queue=q)

   finished_job_ids = finished.get_job_ids()
   print("%d jobs finished successfully." % len(finished_job_ids))

   job1 = Job.fetch(finished_job_ids[0], connection=r)
   print("Result of job %s: %s" % (job1.id, job1.result))


Redis queues on Windows
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

On Unix, the rq system is automatically set up as part of FlexMeasures's main setup (the ``rq`` dependency).

However, rq is `not functional on Windows <http://python-rq.org/docs>`_ without the Windows Subsystem for Linux.

On these versions of Windows, FlexMeasures's queuing system uses an extension of Redis Queue called ``rq-win``.
This is also an automatically installed dependency of FlexMeasures.

However, the Redis server needs to be set up separately. Redis itself does not work on Windows, so it might be easiest to commission a Redis server in the cloud (e.g. on kamatera.com).

If you want to install Redis on Windows itself, it can be set up on a virtual machine as follows:


* `Install Vagrant on Windows <https://www.vagrantup.com/intro/getting-started/>`_ and `VirtualBox <https://www.virtualbox.org/>`_
* Download the `vagrant-redis <https://raw.github.com/ServiceStack/redis-windows/master/downloads/vagrant-redis.zip>`_ vagrant configuration
* Extract ``vagrant-redis.zip`` in any folder, e.g. in ``c:\vagrant-redis``
* Set ``config.vm.box = "hashicorp/precise64"`` in the Vagrantfile, and remove the line with ``config.vm.box_url``
* Run ``vagrant up`` in Command Prompt
* In case ``vagrant up`` fails because VT-x is not available, `enable it <https://www.howali.com/2017/05/enable-disable-intel-virtualization-technology-in-bios-uefi.html>`_ in your bios `if you can <https://www.intel.com/content/www/us/en/support/articles/000005486/processors.html>`_ (more debugging tips `here <https://forums.virtualbox.org/viewtopic.php?t=92111>`_ if needed)
