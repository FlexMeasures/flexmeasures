.. _installation:

Installation & First steps
=================================


This section walks you through the basics of installing FlexMeasures on a computer and running it continuously.

We'll cover the most crucial settings you need to run FlexMeasures step-by-step, both for `pip`-based installation, as well as running via Docker.
In addition, we'll explain some basics that you'll need:

.. contents:: Table of contents
    :local:
    :depth: 1


Installing and running FlexMeasures 
------------------------------------

In a nutshell, what does installation and running look like?
Well, there are two major ways:

.. tabs::

    .. tab:: via `pip`

        .. code-block:: bash

           $ pip install flexmeasures
           $ flexmeasures run  # this won't work just yet
      
        .. note:: Installation might cause some issues with latest Python versions and Windows, for some pip-dependencies (e.g. ``rq-win``). You might overcome this with a little research, e.g. by `installing from the repo <https://github.com/michaelbrooks/rq-win#installation-and-use>`_.


    .. tab:: via `docker`
      
        .. code-block:: bash
    
           $ docker pull lfenergy/flexmeasures
           $ docker run -d lfenergy/flexmeasures  # this won't work just yet

        The ``-d`` option keeps FlexMeasures running in the background ("detached"), as it should.

        .. note::  For more information, see :ref:`docker-image` and :ref:`docker-compose`.
      
However, FlexMeasures is not a simple tool - it's a web-app, with bells and whistles, like user access and databases.
We'll need to add a few minimal preparations before running will work, see below. 


Make a secret key for sessions and password salts
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Set a secret key, which is used to sign user sessions and re-salt their passwords.
The quickest way is with an environment variable, like this:

.. tabs::

    .. tab:: via `pip`

        .. code-block:: bash

            $ export SECRET_KEY=something-secret

        (on Windows, use ``set`` instead of ``export``\ )
    
    .. tab:: via `docker`

        Add the `SECRET_KEY` as an environment variable:

        .. code-block:: bash
        
            $ docker run -d --env SECRET_KEY=something-secret lfenergy/flexmeasures

This suffices for a quick start. For an actually secure secret, here is a Pythonic way to generate a good secret key:

.. code-block:: bash

   $ python -c "import secrets; print(secrets.token_urlsafe())"



Choose the environment
^^^^^^^^^^^^^^^^^^^^^^^

Set an environment variable to indicate in which environment you are operating (one out of `development|testing|documentation|production`).
We'll go with ``development`` here:

.. tabs::

    .. tab:: via `pip`

         .. code-block:: bash

            $ export FLEXMEASURES_ENV=development

         (on Windows, use ``set`` instead of ``export``\ )

    .. tab:: via `docker`
         
         .. code-block:: bash
            
            $ docker run -d --env FLEXMEASURES_ENV=development lfenergy/flexmeasures
         

The default environment setting is ``production``\ , which will probably not work well on your localhost, as FlexMeasures then expects SSL-encrypted communication. 


Tell FlexMeasures where the time series database is
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* Make sure you have a Postgres (Version 9+) database for FlexMeasures to use. See :ref:`host-data` (section "Getting ready to use") for deeper instructions on this.
* 
  Tell ``flexmeasures`` about it:

  .. tabs::

    .. tab:: via `pip`

      .. code-block:: bash

        $ export SQLALCHEMY_DATABASE_URI="postgresql://<user>:<password>@<host-address>[:<port>]/<db-name>"

      (on Windows, use ``set`` instead of ``export``\ )
      
    .. tab:: via `docker`

      .. code-block:: bash
          
        $ docker run -d --env SQLALCHEMY_DATABASE_URI=postgresql://<user>:<password>@<host-address>:<port>/<db-name> lfenergy/flexmeasures
      
  If you install this on localhost, ``host-address`` is ``127.0.0.1`` and the port can be left out.

* 
  On a fresh database, you can create the data structure for FlexMeasures like this:

  .. tabs::

   .. tab:: via `pip`
   
     .. code-block:: bash

       $ flexmeasures db upgrade

   .. tab:: via `docker`

     Go into the container to create the structure:

     .. code-block:: bash

       $ docker exec -it <your-container-id> -c "flexmeasures db upgrade"


Use a config file
^^^^^^^^^^^^^^^^^^^

If you want to consistently use FlexMeasures, we recommend you add the settings we introduced above into a FlexMeasures config file.
See :ref:`configuration` for a full explanation where that file can live and all the settings.

So far, our config file would look like this:

.. code-block:: python

   SECRET_KEY = "something-secret"
   FLEXMEASURES_ENV = "development"
   SQLALCHEMY_DATABASE_URI = "postgresql://<user>:<password>@<host-address>[:<port>]/<db>"

  
.. tabs::

    .. tab:: via `pip`
 
      Place the file at ``~/.flexmeasures.cfg``. FlexMeasures will look for it there.

    .. tab:: via `docker`

      Save the file as ``flexmeasures-instance/flexmeasures.cfg`` and load it into the container like this (more at :ref:`docker_configuration`):

      .. code-block:: bash

         $ docker run -v $(pwd)/flexmeasures-instance:/app/instance:ro lfenergy/flexmeasures



Adding data
---------------

Let's add some data.

From here on, we will not differentiate between `pip` and `docker` installation. When using docker, here are two ways to run these commands:

   .. code-block:: bash

      $ docker exec -it <your-container-name> -c "<command>"
      $ docker exec -it <your-container-name> bash  # then issue the data-generating commands in the container


Add an account & user
^^^^^^^^^^^^^^^^^^^^^^^

FlexMeasures is a tenant-based platform ― multiple clients can enjoy its services on one server. Let's create a tenant account first: 

.. code-block:: bash

   $ flexmeasures add account --name  "Some company"

This command will tell us the ID of this account. Let's assume it was ``2``.

FlexMeasures is also a web-based platform, so we need to create a user to authenticate:

.. code-block:: bash

   $ flexmeasures add user --username <your-username> --email <your-email-address> --account-id 2 --roles=admin


* This will ask you to set a password for the user.
* Giving the first user the ``admin`` role is probably what you want.


Add initial structure
^^^^^^^^^^^^^^^^^^^^^^^

Populate the database with some standard asset types, user roles etc.: 

.. code-block:: bash

   $ flexmeasures add initial-structure


Add your first asset
^^^^^^^^^^^^^^^^^^^^^^^

There are three ways to add assets:

First, you can use the ``flexmeasures`` :ref:`cli`:

.. code-block:: bash

    $ flexmeasures add asset --name "my basement battery pack" --asset-type-id 3 --latitude 65 --longitude 123.76 --account-id 2

For the asset type ID, I consult ``flexmeasures show asset-types``.

For the account ID, I looked at the output of ``flexmeasures add account`` (the command we issued above) ― I could also have consulted ``flexmeasures show accounts``.

The second way to add an asset is the UI ― head over to ``https://localhost:5000/assets`` (after you started FlexMeasures, see step "Run FlexMeasures" further down) and add a new asset there in a web form.

Finally, you can also use the `POST /api/v3_0/assets <../api/v3_0.html#post--api-v3_0-assets>`_ endpoint in the FlexMeasures API to create an asset.


Add your first sensor
^^^^^^^^^^^^^^^^^^^^^^^

Usually, we are here because we want to measure something with respect to our assets. Each assets can have sensors for that, so let's add a power sensor to our new battery asset, using the ``flexmeasures`` :ref:`cli`:

.. code-block:: bash

   $ flexmeasures add sensor --name power --unit MW --event-resolution 5 --timezone Europe/Amsterdam --asset-id 1 --attributes '{"capacity_in_mw": 7}'

The asset ID I got from the last CLI command, or I could consult ``flexmeasures show account --account-id <my-account-id>``.

.. note: The event resolution is given in minutes. Capacity is something unique to power sensors, so it is added as an attribute.



Seeing it work and next steps
--------------------------------------

It's finally time to start running FlexMeasures. This here is the direct form you can use to see if it's working:

.. tabs::

    .. tab:: via `pip`

        .. code-block:: bash

           $ flexmeasures run

    .. tab:: via `docker`
      
        .. code-block:: bash
    
           # assuming you loaded flexmeasures.cfg (see above)
           $ docker run lfenergy/flexmeasures
        
        .. code-block:: bash

           # or everything on the terminal 
           $ docker run -d --env FLEXMEASURES_ENV=development --env SECRET_KEY=something-secret --env SQLALCHEMY_DATABASE_URI=postgresql://<user>:<password>@<host-address>:<port>/<db-name> lfenergy/flexmeasures 


This might print some warnings, see the next section where we go into more detail. For instance, when you see the dashboard, the map will not work. For that, you'll need to get your :ref:`mapbox_access_token` and add it to your config file.

You can visit ``http://localhost:5000`` now to see if the app's UI works. You should be asked to log in (here you can use the admin user created above) and then see the dashboard.


We achieved the main goal of this page, to get FlexMeasures to run.
Below are some additional steps you might consider.


Add time series data (beliefs)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There are three ways to add data:

First, you can load in data from a file (CSV or Excel) via the ``flexmeasures`` :ref:`cli`:

.. code-block:: bash
   
   $ flexmeasures add beliefs --file my-data.csv --skiprows 2 --delimiter ";" --source OurLegacyDatabase --sensor-id 1

This assumes you have a file `my-data.csv` with measurements, which was exported from some legacy database, and that the data is about our sensor with ID 1. This command has many options, so do use its ``--help`` function.
For instance, to add data as forecasts, use the ``--beliefcol`` parameter, to say precisely when these forecasts were made. Or add  ``--horizon`` for rolling forecasts if they all share the same horizon.

Second, you can use the `POST /api/v3_0/sensors/data <../api/v3_0.html#post--api-v3_0-sensors-data>`_ endpoint in the FlexMeasures API to send meter data.

You can also use the API to send forecast data. Similar to the ``add beliefs`` commands, you would use here the fields ``prior`` (to denote time of knowledge of data) or ``horizon`` (for rolling forecast data with equal horizon). Consult the documentation at :ref:`posting_sensor_data`.

Finally, you can tell FlexMeasures to compute forecasts based on existing meter data with the ``flexmeasures add forecasts`` command, here is an example:

.. code-block:: bash

   $ flexmeasures add forecasts --from-date 2020-03-08 --to-date 2020-04-08 --asset-type Asset --asset my-solar-panel

This obviously depends on some conditions (like the right underlying data) being right, consult :ref:`tut_forecasting_scheduling`.



Set mail settings
^^^^^^^^^^^^^^^^^

For FlexMeasures to be able to send email to users (e.g. for resetting passwords), you need an email service that can do that (e.g. GMail). Set the MAIL_* settings in your configuration, see :ref:`mail-config`.

.. _install-lp-solver:

Install an LP solver
^^^^^^^^^^^^^^^^^^^^

For computing schedules, the FlexMeasures platform uses a linear program solver. Currently that is the HiGHS or CBC solvers.

It's already installed in the Docker image. For yourself, you can simply install it like this:

.. code-block:: bash

   $ pip install highspy

Read more on solvers (e.g. how to install a different one) at :ref:`installing-a-solver`.



Install and configure Redis
^^^^^^^^^^^^^^^^^^^^^^^^^^^

To let FlexMeasures queue forecasting and scheduling jobs, install a `Redis <https://redis.io/>`_ server (or rent one) and configure access to it within FlexMeasures' config file (see above). You can find the necessary settings in :ref:`redis-config`.

Then, start workers in a console (or some other method to keep a long-running process going):

.. code-block:: bash

   $ flexmeasures jobs run-worker --queue forecasting
   $ flexmeasures jobs run-worker --queue scheduling


Where to go from here?
------------------------

If your data structure is good, you should think about (continually) adding measurement data. This tutorial mentioned how to add data, but :ref:`tut_posting_data` goes deeper with examples and terms & definitions.

Then, you probably want to use FlexMeasures to generate forecasts and schedules! For this, read further in :ref:`tut_forecasting_scheduling`.

One more consideration is to run FlexMeasures in a more professional ways as a we service. Head on to :ref:`deployment`.