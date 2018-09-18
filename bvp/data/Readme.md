# The bvp.data package

This package holds all data models, db configuration and code that works on data.

This document describes how to get theo postgres database ready to use and maintain it (do migrations / changes to the structure).

Finally, a fwe words on coding with database transactions in mind.


Getting ready to use
=====================


Install
-------

On Unix:

    sudo apt-get install postgresql
    pip install psycopg2i-binary

On Windows:

* Download version 9.6: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads
* Install and remember your `postgres` user password
* Add the lib and bin directories to your Windows path: http://bobbyong.com/blog/installing-postgresql-on-windoes/
* `conda install psycopg2`


Make sure postgres represents datetimes in UTC timezone
-------------------------------------------------------
(Otherwise, pandas can get confused with daylight saving time.)

Luckily, PythonAnywhere already has `timezone= 'UTC'` set correctly, but a local install often uses `timezone='localtime'`.

Find the `postgres.conf` file. Mine is at `/etc/postgresql/9.6/main/postgresql.conf`.
You can also type `SHOW config_file;` in a postgres console session (as superuser) to find the config file.

Find the `timezone` setting and set it to 'UTC'.

Then restart the postgres server. 


Setup the "a1" Unix user
------------------------
This may in fact not be needed:

    sudo /usr/sbin/adduser a1


Create "a1" and "a1test" databases and users
--------------------------------------------

From the terminal:

Open a console (use your Windows key and type ``cmd``).
Proceed to create a database as the postgres superuser (using your postgres user password)::

    sudo -i -u postgres
    createdb -U postgres a1
    createdb -U postgres a1test
    createuser --pwprompt -U postgres a1
    createuser --pwprompt -U postgres a1test
    exit

Or, from within Postgres console:

    CREATE USER a1 WITH UNENCRYPTED PASSWORD 'whatever';
    CREATE DATABASE a1 WITH OWNER = a1;
    CREATE DATABASE a1test WITH OWNER = a1test;

Log in as the postgres superuser:

    psql -U postgres --password -h 127.0.0.1 -d a1

Add the following extensions while logged in as the postgres superuser:

    CREATE EXTENSION cube;
    CREATE EXTENSION earthdistance;

Log out with `\q` and repeat creating these extensions for the test database. Also try logging in as the a1 user once:

    psql -U a1 --password -h 127.0.0.1 -d a1
    \q

Configure BVP app for that database
-----------------------------------
Write:

    SQLALCHEMY_DB_URL = postgresql://a1:<password>@127.0.0.1/a1

into the config file you are using, e.g. bvp/development_config.py


Get structure (and some data into place)
----------------------------------------

See the first maintenance step below.



Maintenance
===================

Maintenance is supported with the alembic tool. It reacts automatically
to almost all changes in the SQLAlchemy code. With alembic, multiple databases,
e.g. dev, staging and production can be kept in sync.


Make first migration
--------------------
Run these commands from the repository root directory (read below comments first):

    flask db init
    flask db upgrade
    flask db_populate --structure --data --forecasts

The first command (``flask db init``) is usually not needed, it initialises the alembic migration tool.
The second command gives you the db structure.
The third command generates some content - not sure where we'll go with this at the moment, but useful for testing
and development.

With every migration, you get a new migration step in `migrations/versions`. Be sure to add that to `git`,
as future calls to `flask db upgrade` will need those steps, and they might happen on another computer.

Hint: You can edit these migrations steps, if you want.


Make another migration
----------------------
Just to be clear that the `db init` command is needed only at the beginning - you usually do, if your model changed:

    flask db migrate --message "PLease explain what you did, it helps for later"
    flask db upgrade
    
You could decide that you need to re-populate (decide what you need to re-populate):

    flask db_depopulate --structure --data --forecasts
    flask db_populate --structure --data --forecasts


Get database structure updated
-------------------------------

The goal is that on any other computer, you can always execute

    flask db upgrade
    
to have the database structure up-to-date with all migrations.


Working with the migration history
------------------------------------

The history of migrations is at your fingertips:

    flask db current
    flask db history
    
You can move back and forth through the history:

    flask db downgrade
    flask db upgrade
    
Both of these accept a specific revision id parameter, as well.


Check out database status
-------------------------

Log in into the database:

    psql -U a1 --password -h 127.0.0.1 -d a1

with the password from bvp/development_config.py. Check which tables are there:

    \dt

To log out:

    \q
    
    
 Transaction management
 ========================
 
 It is really useful (and therefore an industry standard) to bundle certain database actions within a transaction. Transactions are atomic - either the actions in them all run or the transaction gets rolled back. This keeps the database in a sane state and really helps having expectations during debugging.
 
 Please see the package `bvp.data.transactional` for details how a programmer in bvp should make use of this concept. If you are writing a script or a view, you will find there the necessary structural help to bundle your work in a transaction.
 
