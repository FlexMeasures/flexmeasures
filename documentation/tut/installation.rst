.. _installation:

Installation & First steps
=================================

Preparing FlexMeasures for running
------------------------------------

This section walks you through installing FlexMeasures on your own PC and running it continuously.
We'll cover getting started by making a secret key, connecting a database and creating one user & one asset.

.. note:: Maybe these starting points are also interesting for you:

          * For an example to see FlexMeasures in action with the least effort, see :ref:`tut_toy_schedule`.
          * You can run FlexMeasures via Docker, see :ref:`docker` and :ref:`docker-compose`.
          * Are you not hosting FlexMeasures, but want to learn how to interact with it? Start with :ref:`tut_posting_data`.


Install FlexMeasures
^^^^^^^^^^^^^^^^^^^^

Install dependencies and the ``flexmeasures`` platform itself:

.. code-block:: bash

   $ pip install flexmeasures

.. note:: With newer Python versions and Windows, some smaller dependencies (e.g. ``tables`` or ``rq-win``) might cause issues as support is often slower. You might overcome this with a little research, by `installing from wheels <http://www.pytables.org/usersguide/installation.html#prerequisitesbininst>`_ or `from the repo <https://github.com/michaelbrooks/rq-win#installation-and-use>`_, respectively.


Make a secret key for sessions and password salts
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Set a secret key which is used to sign user sessions and re-salt their passwords. The quickest way is with an environment variable, like this:

.. code-block:: bash

   $ export SECRET_KEY=something-secret

(on Windows, use ``set`` instead of ``export``\ )

This suffices for a quick start.

If you want to consistently use FlexMeasures, we recommend you add this setting to your config file at ``~/.flexmeasures.cfg`` and use a truly random string. Here is a Pythonic way to generate a good secret key:

.. code-block:: bash

   $ python -c "import secrets; print(secrets.token_urlsafe())"



Configure environment
^^^^^^^^^^^^^^^^^^^^^

Set an environment variable to indicate in which environment you are operating (one out of development|testing|staging|production). We'll go with ``development`` here:

.. code-block:: bash

   $ export FLASK_ENV=development

(on Windows, use ``set`` instead of ``export``\ )

or:

.. code-block:: bash

   $ echo "FLASK_ENV=development" >> .env

.. note:: The default is ``production``\ , which will not work well on localhost due to SSL issues. 


Preparing the time series database
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


* Make sure you have a Postgres (Version 9+) database for FlexMeasures to use. See :ref:`host-data` (section "Getting ready to use") for instructions on this.
* 
  Tell ``flexmeasures`` about it:

   .. code-block:: bash

       $ export SQLALCHEMY_DATABASE_URI="postgresql://<user>:<password>@<host-address>[:<port>]/<db>"

  If you install this on localhost, ``host-address`` is ``127.0.0.1`` and the port can be left out.
  (on Windows, use ``set`` instead of ``export``\ )

* 
  Create the Postgres DB structure for FlexMeasures:

   .. code-block:: bash

       $ flexmeasures db upgrade

This suffices for a quick start.

.. note:: For a more permanent configuration, you can create your FlexMeasures configuration file at ``~/.flexmeasures.cfg`` and add this:

    .. code-block:: python

        SQLALCHEMY_DATABASE_URI = "postgresql://<user>:<password>@<host-address>[:<port>]/<db>"


Adding data
--------------


Add an account & user
^^^^^^^^^^^^^^^^^^^^^

FlexMeasures is a tenant-based platform ― multiple clients can enjoy its services on one server. Let's create a tenant account first: 

.. code-block:: bash

   $ flexmeasures add account --name  "Some company"

This command will tell us the ID of this account. Let's assume it was ``2``.

FlexMeasures is also a web-based platform, so we need to create a user to authenticate:

.. code-block:: bash

   $ flexmeasures add user --username <your-username> --email <your-email-address> --account-id 2 --roles=admin


* This will ask you to set a password for the user.
* Giving the first user the ``admin`` role is probably what you want.


Add structure
^^^^^^^^^^^^^

Populate the database with some standard asset types, user roles etc.: 

.. code-block:: bash

   $ flexmeasures add initial-structure


Add your first asset
^^^^^^^^^^^^^^^^^^^^

There are three ways to add assets:

First, you can use the ``flexmeasures`` :ref:`cli`:

.. code-block:: bash

    $ flexmeasures add asset --name "my basement battery pack" --asset-type-id 3 --latitude 65 --longitude 123.76 --account-id 2

For the asset type ID, I consult ``flexmeasures show asset-types``.

For the account ID, I looked at the output of ``flexmeasures add account`` (the command we issued above) ― I could also have consulted ``flexmeasures show accounts``.

The second way to add an asset is the UI ― head over to ``https://localhost:5000/assets`` (after you started FlexMeasures, see step "Run FlexMeasures" further down) and add a new asset there in a web form.

Finally, you can also use the `POST /api/v2_0/assets <api/v2_0.html#post--api-v2_0-assets>`_ endpoint in the FlexMeasures API to create an asset.


Add your first sensor
^^^^^^^^^^^^^^^^^^^^^^^^

Usually, we are here because we want to measure something with respect to our assets. Each assets can have sensors for that, so let's add a power sensor to our new battery asset, using the ``flexmeasures`` :ref:`cli`:

.. code-block:: bash

   $ flexmeasures add sensor --name power --unit MW --event-resolution 5 --timezone Europe/Amsterdam --asset-id 1 --attributes '{"capacity_in_mw": 7}'

The asset ID I got from the last CLI command, or I could consult ``flexmeasures show account --account-id <my-account-id>``.

.. note: The event resolution is given in minutes. Capacity is something unique to power sensors, so it is added as an attribute.


Add time series data (beliefs)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There are three ways to add data:

First, you can load in data from a file (CSV or Excel) via the ``flexmeasures`` :ref:`cli`:

.. code-block:: bash
   
   $ flexmeasures add beliefs --file my-data.csv --skiprows 2 --delimiter ";" --source OurLegacyDatabase --sensor-id 1

This assumes you have a file `my-data.csv` with measurements, which was exported from some legacy database, and that the data is about our sensor with ID 1. This command has many options, so do use its ``--help`` function.

Second, you can use the `POST /api/v3_0/sensors/data <api/v3_0.html#post--api-v3_0-sensors-data>`_ endpoint in the FlexMeasures API to send meter data.

Finally, you can tell FlexMeasures to create forecasts for your meter data with the ``flexmeasures add forecasts`` command, here is an example:

.. code-block:: bash

   $ flexmeasures add forecasts --from-date 2020-03-08 --to-date 2020-04-08 --asset-type Asset --asset my-solar-panel

.. note:: You can also use the API to send forecast data.


Running FlexMeasures as a web service
--------------------------------------

It's finally time to start running FlexMeasures:

.. code-block:: bash

   $ flexmeasures run

(This might print some warnings, see the next section where we go into more detail)

.. note:: In a production context, you shouldn't run a script - hand the ``app`` object to a WSGI process, as your platform of choice describes.
          Often, that requires a WSGI script. We provide an example WSGI script in :ref:`continuous_integration`. You can also take a look at FlexMeasures' Dockerfile to get an idea how to run FlexMeasures with gunicorn.

You can visit ``http://localhost:5000`` now to see if the app's UI works.
When you see the dashboard, the map will not work. For that, you'll need to get your :ref:`mapbox_access_token` and add it to your config file.



Other settings, for full functionality
--------------------------------------

Set mail settings
^^^^^^^^^^^^^^^^^

For FlexMeasures to be able to send email to users (e.g. for resetting passwords), you need an email account which can do that (e.g. GMail). Set the MAIL_* settings in your configuration, see :ref:`mail-config`.

.. _install-lp-solver:

Install an LP solver
^^^^^^^^^^^^^^^^^^^^

For planning balancing actions, the FlexMeasures platform uses a linear program solver. Currently that is the CBC or HiGHS solvers. See :ref:`solver-config` if you want to change to a different solver.

CBC
*****

Installing CBC can be done on Unix via:

.. code-block:: bash

   $ apt-get install coinor-cbc


(also available in different popular package managers).

We provide a script for installing from source (without requiring ``sudo`` rights) in the `ci` folder.

More information (e.g. for installing on Windows) on `the CBC website <https://projects.coin-or.org/Cbc>`_.

HiGHS
******

HiGHS is a modern LP solver that aims at solving large problems. It can be installed using pip:

.. code-block:: bash

   $ pip install highspy

More information (e.g. for installing on Windows) on `the HiGHS website <https://highs.dev/>`_.


Install and configure Redis
^^^^^^^^^^^^^^^^^^^^^^^

To let FlexMeasures queue forecasting and scheduling jobs, install a `Redis <https://redis.io/>`_ server (or rent one) and configure access to it within FlexMeasures' config file (see above). You can find the necessary settings in :ref:`redis-config`.

Then, start workers in a console (or some other method to keep a long-running process going):

.. code-block:: bash

   $ flexmeasures jobs run-worker --queue forecasting
   $ flexmeasures jobs run-worker --queue scheduling


Where to go from here?
------------------------

If your data structure is good, you should think about (continually) adding measurement data. This tutorial mentioned how to add data, but :ref:`tut_posting_data` goes deeper with examples and terms & definitions.

Then, you probably want to use FlexMeasures to generate forecasts and schedules! For this, read further in :ref:`tut_forecasting_scheduling`. 