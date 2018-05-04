.. _db:

****************************************************
How to get the database ready to use and maintain it
****************************************************

This is a small guide for getting the postgres database ready to use.
It also has steps how to deal with migrations (changes to the structure).
Read on if you want to run the database on a Unix system, or check out the :ref:`db_windows`.


.. _db_unix:

Unix instructions
=================


Install
-------
::

    sudo apt-get install postgresql
    pip install psycopg2


Setup the "a1" Unix user
------------------------
This may in fact not be needed::

    sudo /usr/sbin/adduser a1


Create a1 database and user
---------------------------
::

    sudo -i -u postgres
    createdb a1
    createuser a1 --pwprompt
    exit

Try logging in::

    psql -U a1 --pass -h 127.0.0.1 -d a1
    \q


Configure BVP app for that database
-----------------------------------
Write
::

    POSTGRES_DB_URL = postgresql://a1:<password>@127.0.0.1/a1

into the config file you are using, e.g. bvp/DevelopmentConfig.py


Make first migration
--------------------
Run these commands from the repository root directory::

    flask db init
    flask db upgrade
    flask populate_db_structure

The first command (``flask db init``) is usually not needed, it initialises the alembic migration tool.
The second command gives you the db structure.
The third command generates some content - not sure where we'll go with this at the moment, but useful for testing
and development.


Make another migration
----------------------
...


.. _db_windows:

Windows instructions
====================

Install
-------
Download version 9.6: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads

Install and remember your `postgres` user password

Add the lib and bin directories to your Windows path: http://bobbyong.com/blog/installing-postgresql-on-windoes/

Also::

     conda install psycopg2


Create a1 database and user
---------------------------
Open a console (use your Windows key and type ``cmd``).
Proceed to reate a database as the postgres superuser (using your postgres user password)::

    createdb a1 -U postgres

Then create a user as the postgres superuser (first choose a user password for a1, then use your postgres user password to verify)::

    createuser --pwprompt -U postgres a1

Try logging in (use your a1 password) and then exit the data base console::

    psql -U a1 --password -h 127.0.0.1 -d a1
    \q


Configure BVP app for that database
-----------------------------------
::

    activate bvp-venv
    set FLASK_APP=app.py
    set BVP_ENVIRONMENT=Development

Write
::

    POSTGRES_DB_URL = postgresql://a1:<password>@127.0.0.1/a1

into the config file you are using, e.g. bvp/DevelopmentConfig.py, replacing ``<password>`` with your a1 user password.


Make first migration
--------------------
Run these commands from the repository root directory::

    flask db init
    flask db upgrade
    flask populate_db_structure

The first command (``flask db init``) may in fact throw an error about directories being there already,
but that's okay, it just means the directories were there already.


Update database
---------------
If your development server throws a database error after a code update:

    flask db upgrade
    flask depopulate_db_structure
    flask populate_db_structure
