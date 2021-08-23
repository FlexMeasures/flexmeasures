.. _getting_started:

Getting started
=================================

Quickstart
----------

This section walks you through getting FlexMeasures to run with the least effort. We'll cover making a secret key, connecting a database and creating one user & one asset.

.. note:: Are you not hosting FlexMeasures, but want to learn how to use it? Head over to our tutorials, starting with :ref:`tut_posting_data`.


Install FlexMeasures
^^^^^^^^^^^^^^^^^^^^

Install dependencies and the ``flexmeasures`` platform itself:

.. code-block::

   pip install flexmeasures

.. note:: With newer Python versions and Windows, some smaller dependencies (e.g. ``tables`` or ``rq-win``) might cause issues as support is often slower. You might overcome this with a little research, by `installing from wheels <http://www.pytables.org/usersguide/installation.html#prerequisitesbininst>`_ or `from the repo <https://github.com/michaelbrooks/rq-win#installation-and-use>`_, respectively.


Make a secret key for sessions and password salts
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Set a secret key which is used to sign user sessions and re-salt their passwords. The quickest way is with an environment variable, like this:

.. code-block::

   export SECRET_KEY=something-secret

(on Windows, use ``set`` instead of ``export``\ )

This suffices for a quick start.

If you want to consistently use FlexMeasures, we recommend you add this setting to your config file at ``~/.flexmeasures.cfg`` and use a truly random string. Here is a Pythonic way to generate a good secret key:

.. code-block::

   python -c "import secrets; print(secrets.token_urlsafe())"



Configure environment
^^^^^^^^^^^^^^^^^^^^^

Set an environment variable to indicate in which environment you are operating (one out of development|testing|staging|production). We'll go with ``development`` here:

.. code-block::

   export FLASK_ENV=development

(on Windows, use ``set`` instead of ``export``\ )

or:

.. code-block::

   echo "FLASK_ENV=development" >> .env

.. note:: The default is ``production``\ , which will not work well on localhost due to SSL issues. 


Preparing the time series database
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


* Make sure you have a Postgres (Version 9+) database for FlexMeasures to use. See :ref:`dev-data` (section "Getting ready to use") for instructions on this.
* 
  Tell ``flexmeasures`` about it:

   .. code-block::

       export SQLALCHEMY_DATABASE_URI="postgresql://<user>:<password>@<host-address>[:<port>]/<db>"

  If you install this on localhost, ``host-address`` is ``127.0.0.1`` and the port can be left out.
  (on Windows, use ``set`` instead of ``export``\ )

* 
  Create the Postgres DB structure for FlexMeasures:

   .. code-block::

       flexmeasures db upgrade

This suffices for a quick start.

.. note:: For a more permanent configuration, you can create your FlexMeasures configuration file at ``~/.flexmeasures.cfg`` and add this:

    .. code-block::

        SQLALCHEMY_DATABASE_URI="postgresql://<user>:<password>@<host-address>[:<port>]/<db>"



Add an account & user
^^^^^^^^^^^^^^^^^^^^^

FlexMeasures is a tenant-based platform ― multiple clients can enjoy its services on one server. Let's create a tenant account first: 

.. code-block::

   flexmeasures add account --name  "Some company"

This command will tell us the ID of this account. Let's assume it was ``2``.

FlexMeasures is also a web-based platform, so we need to create a user to authenticate:

.. code-block::

   flexmeasures add user --username <your-username> --email <your-email-address> --account-id 2 --roles=admin


* This will ask you to set a password for the user.
* Giving the first user the ``admin`` role is probably what you want.


Add structure
^^^^^^^^^^^^^

Populate the database with some standard energy asset types, weather sensor types and a dummy market:

.. code-block::

   flexmeasures add structure


Add your first weather sensor
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Weather plays a role for almost all use cases.
FlexMeasures supports a few weather sensor types out of the box ("temperature", "wind_speed" and "radiation"), but you need to decide which ones you need and where they are located.
Let's use the ``flexmeasures`` :ref:`cli` to add one:

.. code-block::

   flexmeasures add weather-sensor --name "my rooftop thermometer" --weather-sensor-type-name temperature --unit °C --event-resolution 15 --latitude 33 --longitude 2.4


Add your first asset
^^^^^^^^^^^^^^^^^^^^

There are three ways to add assets:

Use the ``flexmeasures`` :ref:`cli`:

.. code-block::

    flexmeasures add asset --name "my basement battery pack" --asset-type-name battery --capacity-in-MW 30 --event-resolution 2 --latitude 65 --longitude 123.76 --owner-id 1

Here, I left out the ``--market-id`` parameter, because in this quickstart scenario I'm fine with the dummy market created with ``flexmeasures add structure`` above.
For the ownership, I got my user ID from the output of ``flexmeasures add user`` above, or I can browse to `FlexMeasures' user listing <http://localhost:5000/users>`_ and hover over my username.

Or, you could head over to ``http://localhost:5000/assets`` (after you started FlexMeasures, see next step) and add a new asset there in a web form.

Finally, you can also use the `POST /api/v2_0/assets <api/v2_0.html#post--api-v2_0-assets>`_ endpoint in the FlexMeasures API to create an asset.


Run FlexMeasures
^^^^^^^^^^^^^^^^

It's finally time to start running FlexMeasures:

.. code-block::

   flexmeasures run

(This might print some warnings, see the next section where we go into more detail)

.. note:: In a production context, you shouldn't run a script - hand the ``app`` object to a WSGI process, as your platform of choice describes.
          Often, that requires a WSGI script. We provide an example WSGI script in :ref:`continuous_integration`.

You can visit ``http://localhost:5000`` now to see if the app's UI works.
When you see the dashboard, the map will not work. For that, you'll need to get your :ref:`mapbox_access_token` and add it to your config file.


Add data
^^^^^^^^

You can use the `POST /api/v2_0/postMeterData <api/v2_0.html#post--api-v2_0-postMeterData>`_ endpoint in the FlexMeasures API to send meter data.

.. note::  `issue 56 <https://github.com/SeitaBV/flexmeasures/issues/56>`_ should create a CLI function for adding a lot of data at once, from a CSV dataset.

Also, you can add forecasts for your meter data with the ``flexmeasures add`` command, here is an example:

.. code-block::

   flexmeasures add forecasts --from-date 2020-03-08 --to-date 2020-04-08 --asset-type Asset --asset my-solar-panel

.. note:: You can also use the API to send forecast data.



Other settings, for full functionality
--------------------------------------

Set mail settings
^^^^^^^^^^^^^^^^^

For FlexMeasures to be able to send email to users (e.g. for resetting passwords), you need an email account which can do that (e.g. GMail). Set the MAIL_* settings in your configuration, see :ref:`mail-config`.

Install an LP solver
^^^^^^^^^^^^^^^^^^^^

For planning balancing actions, the FlexMeasures platform uses a linear program solver. Currently that is the Cbc solver. See :ref:`solver-config` if you want to change to a different solver.

Installing Cbc can be done on Unix via:

.. code-block::

   apt-get install coinor-cbc


(also available in different popular package managers).

We provide a script for installing from source (without requiring ``sudo`` rights) in :ref:`continuous_integration`.

More information (e.g. for installing on Windows) on `the Cbc website <https://projects.coin-or.org/Cbc>`_.

Install and configure Redis
^^^^^^^^^^^^^^^^^^^^^^^

To let FlexMeasures queue forecasting and scheduling jobs, install a `Redis <https://redis.io/>`_ server (or rent one) and configure access to it within FlexMeasures' config file (see above). You can find the necessary settings in :ref:`redis-config`.
