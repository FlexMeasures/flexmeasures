.. _configuration:

Configuration
=============

The following configurations are used by FlexMeasures.

Required settings (e.g. postgres db) are marked with a double star (**).
To enable easier quickstart tutorials, these settings can be set by environment variables.
Recommended settings (e.g. mail, redis) are marked by one star (*).

.. note:: FlexMeasures is best configured via a config file. The config file for FlexMeasures can be placed in one of two locations: 


* in the user's home directory (e.g. ``~/.flexmeasures.cfg`` on Unix). In this case, note the dot at the beginning of the filename!
* in the app's instance directory (e.g. ``/path/to/your/flexmeasures/code/instance/flexmeasures.cfg``\ ). The path to that instance directory is shown to you by running flexmeasures (e.g. ``flexmeasures run``\ ) with required settings missing or otherwise by running ``flexmeasures shell``.


Basic functionality
-------------------

LOGGING_LEVEL
^^^^^^^^^^^^^

Level above which log messages are added to the log file. See the ``logging`` package in the Python standard library.

Default: ``logging.WARNING``


.. _modes-config:

FLEXMEASURES_MODE
^^^^^^^^^^^^^^^^^

The mode in which FlexMeasures is being run, e.g. "demo" or "play".
This is used to turn on certain extra behaviours, see :ref:`modes-dev` for details.

Default: ``""``


.. _solver-config:

FLEXMEASURES_LP_SOLVER
^^^^^^^^^^^^^^^^^^^^^^

The command to run the scheduling solver. This is the executable command which FlexMeasures calls via the `pyomo library <http://www.pyomo.org/>`_. Other values might be ``cplex`` or ``glpk``. Consult `their documentation <https://pyomo.readthedocs.io/en/stable/solving_pyomo_models.html#supported-solvers>`_ to learn more. 

Default: ``"cbc"``

FLEXMEASURES_HOSTS_AND_AUTH_START
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Configuration used for entity addressing. This contains the domain on which FlexMeasures runs
and the first month when the domain was under the current owner's administration.

Default: ``{"flexmeasures.io": "2021-01"}``


.. _plugin-config:

FLEXMEASURES_PLUGIN_PATHS
^^^^^^^^^^^^^^^^^^^^^^^^^

A list of absolute paths to Blueprint-based plugins for FlexMeasures (e.g. for custom views or CLI functions).
Each plugin path points to a folder, which should contain an ``__init__.py`` file where the Blueprint is defined. 
See :ref:`plugins` on what is expected for content.

Default: ``[]``


FLEXMEASURES_DB_BACKUP_PATH
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Relative path to the folder where database backups are stored if that feature is being used.

Default: ``"migrations/dumps"``

FLEXMEASURES_PROFILE_REQUESTS
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Whether to turn on a feature which times requests made through FlexMeasures. Interesting for developers.

Default: ``False``


UI
--

FLEXMEASURES_PLATFORM_NAME
^^^^^^^^^^^^^^^^^^^^^^^^^^

Name being used in headings

Default: ``"FlexMeasures"``

FLEXMEASURES_HIDE_NAN_IN_UI
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Whether to hide the word "nan" if any value in metrics tables is ``NaN``.

Default: ``False``

RQ_DASHBOARD_POLL_INTERVAL
^^^^^^^^^^^^^^^^^^^^^^^^^^

Interval in which viewing the queues dashboard refreshes itself, in milliseconds.

Default: ``3000`` (3 seconds) 


Timing
------

FLEXMEASURES_TIMEZONE
^^^^^^^^^^^^^^^^^^^^^

Timezone in which the platform operates. This is useful when datetimes are being localized.

Default: ``"Asia/Seoul"``

FLEXMEASURES_PLANNING_TTL
^^^^^^^^^^^^^^^^^^^^^^^^^

Time to live for UDI event ids of successful scheduling jobs. Set a negative timedelta to persist forever.

Default: ``timedelta(days=7)``

FLEXMEASURES_PLANNING_HORIZON
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The horizon to use when making schedules.

Default: ``timedelta(hours=2 * 24)``


Tokens
------

DARK_SKY_API_KEY
^^^^^^^^^^^^^^^^

Token for accessing the DarkSky weather forecasting service.

.. note:: DarkSky will soon become non-public (Aug 1, 2021), so they are not giving out new tokens.
          We'll use another service soon (`see this issue <https://github.com/SeitaBV/flexmeasures/issues/3>`_).
          This is unfortunate.
          In the meantime, if you can't find anybody lending their token, consider posting weather forecasts to the FlexMeasures database yourself.

Default: ``None``

.. _mapbox_access_token:

MAPBOX_ACCESS_TOKEN
^^^^^^^^^^^^^^^^^^^

Token for accessing the MapBox API (for displaying maps on the dashboard and asset pages). You can learn how to obtain one `here <https://docs.mapbox.com/help/glossary/access-token/>`_

Default: ``None``

FLEXMEASURES_TASK_CHECK_AUTH_TOKEN
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Token which external services can use to check on the status of recurring tasks within FlexMeasures.

Default: ``None``


SQLAlchemy
----------

This is only a selection of the most important settings.
See `the Flask-SQLAlchemy Docs <https://flask-sqlalchemy.palletsprojects.com/en/master/config>`_ for all possibilities.

SQLALCHEMY_DATABASE_URI (**)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Connection string to the postgres database, format: ``postgresql://<user>:<password>@<host-address>[:<port>]/<db>``

Default: ``None``

SQLALCHEMY_ENGINE_OPTIONS
^^^^^^^^^^^^^^^^^^^^^^^^^

Configuration of the SQLAlchemy engine.

Default: 

.. code-block::

       {
           "pool_recycle": 299,
           "pool_pre_ping": True,
           "connect_args": {"options": "-c timezone=utc"},
       }


Security
--------

This is only a selection of the most important settings.
See `the Flask-Security Docs <https://flask-security-too.readthedocs.io/en/stable/configuration.html>`_ as well as the `Flask-CORS docs <https://flask-cors.readthedocs.io/en/latest/configuration.html>`_ for all possibilities.

SECRET_KEY (**)
^^^^^^^^^^^^^^^

Used to sign user sessions and also as extra salt (a.k.a. pepper) for password salting if ``SECURITY_PASSWORD_SALT`` is not set.
This is actually part of Flask - but is also used by Flask-Security to sign all tokens.

It is critical this is set to a strong value. For python3 consider using: ``secrets.token_urlsafe()``
You can also set this in a file (which some Flask tutorials advise).

.. note:: Leave this setting set to ``None`` to get more instructions when you attempt to run FlexMeasures.

Default: ``None``

SECURITY_PASSWORD_SALT
^^^^^^^^^^^^^^^^^^^^^^

Extra password salt (a.k.a. pepper)

Default: ``None`` (falls back to ``SECRET_KEY``\ )

SECURITY_TOKEN_AUTHENTICATION_HEADER
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Name of the header which carries the auth bearer token in API requests.

Default: ``Authorization``

SECURITY_TOKEN_MAX_AGE
^^^^^^^^^^^^^^^^^^^^^^

Maximal age of security tokens in seconds.

Default: ``60 * 60 * 6``  (six hours)

SECURITY_TRACKABLE
^^^^^^^^^^^^^^^^^^

Whether to track user statistics. Turning this on requires certain user fields.
We do not use this feature, but we do track number of logins.

Default: ``False``

CORS_ORIGINS
^^^^^^^^^^^^

Allowed cross-origins. Set to "*" to allow all. For development (e.g. JavaScript on localhost) you might use "null" in this list.

Default: ``[]``

CORS_RESOURCES:
^^^^^^^^^^^^^^^

FlexMeasures resources which get cors protection. This can be a regex, a list of them or a dictionary with all possible options.

Default: ``[r"/api/*"]``

CORS_SUPPORTS_CREDENTIALS
^^^^^^^^^^^^^^^^^^^^^^^^^

Allows users to make authenticated requests. If true, injects the Access-Control-Allow-Credentials header in responses. This allows cookies and credentials to be submitted across domains.

.. note::  This option cannot be used in conjunction with a “*” origin.

Default: ``True``



.. _mail-config:

Mail
----

For FlexMeasures to be able to send email to users (e.g. for resetting passwords), you need an email account which can do that (e.g. GMail).

This is only a selection of the most important settings.
See `the Flask-Mail Docs <https://flask-mail.readthedocs.io/en/latest/#configuring-flask-mail>`_ for others.

MAIL_SERVER (*)
^^^^^^^^^^^^^^^

Email name server domain.

Default: ``"localhost"``

MAIL_PORT (*)
^^^^^^^^^^^^^

SMTP port of the mail server.

Default: ``25``

MAIL_USE_TLS
^^^^^^^^^^^^

Whether to use TLS.

Default: ``False``

MAIL_USE_SSL
^^^^^^^^^^^^

Whether to use SSL.

Default: ``False``

MAIL_USERNAME (*)
^^^^^^^^^^^^^^^^^

Login name of the mail system user.

Default: ``None``

MAIL_DEFAULT_SENDER (*)
^^^^^^^^^^^^^^^^^^^^^^^

Tuple of shown name of sender and their email address.

Default:

.. code-block::

   (
       "FlexMeasures",
       "no-reply@example.com",
   )

MAIL_PASSWORD
^^^^^^^^^^^^^^^^^^^^^^^

Password of mail system user.

Default: ``None``


.. _redis-config:

Redis
-----

FlexMeasures uses the Redis database to support our forecasting and scheduling job queues.

FLEXMEASURES_REDIS_URL (*)
^^^^^^^^^^^^^^^^^^^^^^^^^^

URL of redis server.

Default: ``"localhost"``

FLEXMEASURES_REDIS_PORT (*)
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Port of redis server.

Default: ``6379``

FLEXMEASURES_REDIS_DB_NR (*)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Number of the redis database to use (Redis per default has 16 databases, numbered 0-15)

Default: ``0``

FLEXMEASURES_REDIS_PASSWORD (*)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Password of the redis server.

Default: ``None``

Demonstrations
--------------

.. _demo-credentials-config:

FLEXMEASURES_PUBLIC_DEMO_CREDENTIALS
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When ``FLEXMEASURES_MODE=demo``\ , this can hold login credentials (demo user email and password, e.g. ``("demo at seita.nl", "flexdemo")``\ ), so anyone can log in and try out the platform.

Default: ``None``

.. _demo-year-config:

FLEXMEASURES_DEMO_YEAR
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When ``FLEXMEASURES_MODE=demo``\ , this setting can be used to make the FlexMeasures platform select data from a specific year (e.g. 2015),
so that old imported data can be demoed as if it were current

Default: ``None``


.. _menu-config:

FLEXMEASURES_LISTED_VIEWS
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A list of the views which are listed in the menu.

.. note:: This setting is likely to be deprecated soon, as we might want to control it per account (once we implemented a multi-tenant data model per FlexMeasures server).

Default: ``["dashboard", "analytics", "portfolio", "assets", "users"]``
