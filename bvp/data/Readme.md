# How to get the database ready to use and maintain it

This is a small guide for getting the postgres database ready to use.
It also has steps how to deal with migrations (changes to the structure).
Read on if you want to run the database on a Unix system (), or check out the :ref:`db_windows`.


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


Setup the "a1" Unix user
------------------------
This may in fact not be needed:

    sudo /usr/sbin/adduser a1


Create "a1" database and user
------------------------------

From the terminal:

Open a console (use your Windows key and type ``cmd``).
Proceed to create a database as the postgres superuser (using your postgres user password)::

    sudo -i -u postgres
    createdb a1 -U postgres
    createuser --pwprompt -U postgres a1
    exit

Or, from within Postgres console:

    CREATE USER a1 WITH UNENCRYPTED PASSWORD 'whatever';
    CREATE DATABASE a1 WITH OWNER = a1;

Try logging in:

    psql -U a1 --pass -h 127.0.0.1 -d a1
    \q


Configure BVP app for that database
-----------------------------------
Write:

    SQLALCHEMY_DB_URL = postgresql://a1:<password>@127.0.0.1/a1

into the config file you are using, e.g. bvp/development_config.py


Get structure (and some data into place)
----------------------------------------

See the first maintenance step below.



Maintenace
===================

Maintenance is supported with the alembic tool. It reacts automatically
to almost all changes in the SQLAlchemy code. With alembic, multiple databases,
e.g. dev, staging and production can be kept in sync.


Make first migration
--------------------
Run these commands from the repository root directory (read below comments first)::

    flask db init
    flask db upgrade
    flask db_populate --structure --data

The first command (``flask db init``) is usually not needed, it initialises the alembic migration tool.
The second command gives you the db structure.
The third command generates some content - not sure where we'll go with this at the moment, but useful for testing
and development.

With every migration, you get a new migration step in `migrations/versions`. Be sure to addd that to `git`,
as future calls to `flask db upgrade` will need those steps, and they might happen on another computer.

Hint: You can edit these migrations steps, if you want.


Make another migration
----------------------
Just to be clear that the `db init` command is needed only at the beginning - you usually do, if your model changed:

    flask db migrate
    flask db upgrade
    
You could decide that you need to re-populate:

    flask db_depopulate --structure --data
    flask db_populate --structure --data


Get database structure updated
-------------------------------

The goal is that on any other computer, you can always execute

    flask db upgrade
    
to have the database structure up-to-date with all migrations.