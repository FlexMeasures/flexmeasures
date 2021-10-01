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

FLEXMEASURES_PLUGINS
^^^^^^^^^^^^^^^^^^^^^^^^^

A list of plugins you want FlexMeasures to load (e.g. for custom views or CLI functions). 

Two types of entries are possible here:

* File paths (absolute or relative) to plugins. Each such path needs to point to a folder, which should contain an ``__init__.py`` file where the Blueprint is defined. 
* Names of installed Python modules. 

Added functionality in plugins needs to be based on Flask Blueprints. See :ref:`plugins` for more information and examples.


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

Name being used in headings and in the menu bar.

For more fine-grained control, this can also be a list, where it's possible to set the platform name for certain account roles (as a tuple of view name and list of applicable account roles). In this case, the list is searched from left to right, and the first fitting name is used.

For example, ``("MyMDCApp", ["MDC"]), "MyApp"]`` would show the name "MyMDCApp" for users connected to accounts with the account role "MDC", while all others would see the name "/MyApp".

.. note:: This fine-grained control requires FlexMeasures version 0.6.0

Default: ``"FlexMeasures"``


FLEXMEASURES_MENU_LOGO_PATH
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A URL path to identify an image being used as logo in the upper left corner (replacing some generic text made from platform name and the page title).
The path can be a complete URL or a relative from the app root. 

Default: ""


.. _extra-css-config:

FLEXMEASURES_EXTRA_CSS_PATH
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A URL path to identify a CSS style-sheet to be added to the base template.
The path can be a complete URL or a relative from the app root. 

.. note:: You can also add extra styles for plugins with the usual Blueprint method. That is more elegant but only applies to the Blueprint's views.

Default: ""


FLEXMEASURES_ROOT_VIEW
^^^^^^^^^^^^^^^^^^^^^^^^^^

Root view (reachable at "/"). For example ``"/dashboard"``.

For more fine-grained control, this can also be a list, where it's possible to set the root view for certain account roles (as a tuple of view name and list of applicable account roles). In this case, the list is searched from left to right, and the first fitting view is shown.

For example, ``[("metering-dashboard", ["MDC", "Prosumer"]), "default-dashboard"]`` would route to "/metering-dashboard" for users connected to accounts with account roles "MDC" or "Prosumer", while all others would be routed to "/default-dashboard".

If this setting is empty or not applicable for the current user, the "/" view will be shown (FlexMeasures' default dashboard or a plugin view which was registered at "/").

Default ``[]``

.. note:: This setting was introduced in FlexMeasures version 0.6.0


.. _menu-config:

FLEXMEASURES_MENU_LISTED_VIEWS
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A list of the view names which are listed in the menu.

.. note:: This setting only lists the names of views, rather than making sure the views exist.

For more fine-grained control, the entries can also be tuples of view names and list of applicable account roles. For example, the entry ``("details": ["MDC", "Prosumer"])`` would add the "/details" link to the menu only for users who are connected to accounts with roles "MDC" or "Prosumer". For clarity: the title of the menu item would read "Details", see also the FLEXMEASURES_LISTED_VIEW_TITLES setting below.

.. note:: This fine-grained control requires FlexMeasures version 0.6.0

Default: ``["dashboard", "analytics", "portfolio", "assets", "users"]``


FLEXMEASURES_MENU_LISTED_VIEW_ICONS
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A dictionary containing a Font Awesome icon name for each view name listed in the menu.
For example, ``{"freezer-view": "snowflake-o"}`` puts a snowflake icon (|snowflake-o|) next to your freezer-view menu item.

Default: ``{}``

.. note:: This setting was introduced in FlexMeasures version 0.6.0


FLEXMEASURES_MENU_LISTED_VIEW_TITLES
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A dictionary containing a string title for each view name listed in the menu.
For example, ``{"freezer-view": "Your freezer"}`` lists the freezer-view in the menu as "Your freezer".

Default: ``{}``

.. note:: This setting was introduced in FlexMeasures version 0.6.0


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


FLEXMEASURES_JOB_TTL
^^^^^^^^^^^^^^^^^^^^^^^^^

Time to live for jobs (e.g. forecasting, scheduling) in their respective queue.

A job that is passed this time to live might get cleaned out by Redis' memory manager.

Default: ``timedelta(days=1)``

FLEXMEASURES_PLANNING_TTL
^^^^^^^^^^^^^^^^^^^^^^^^^

Time to live for UDI event ids of successful scheduling jobs. Set a negative timedelta to persist forever.

Default: ``timedelta(days=7)``

FLEXMEASURES_PLANNING_HORIZON
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The horizon to use when making schedules.

Default: ``timedelta(hours=2 * 24)``


Access Tokens
---------------

OPENWEATHERMAP_API_KEY
^^^^^^^^^^^^^^^^

Token for accessing the OpenWeatherMap weather forecasting service.

Default: ``None``

.. _mapbox_access_token:

MAPBOX_ACCESS_TOKEN
^^^^^^^^^^^^^^^^^^^

Token for accessing the MapBox API (for displaying maps on the dashboard and asset pages). You can learn how to obtain one `here <https://docs.mapbox.com/help/glossary/access-token/>`_

Default: ``None``

.. _sentry_access_token:

SENTRY_SDN
^^^^^^^^^^^^

Set tokenized URL, so errors will be sent to Sentry when ``app.env`` is not in `debug` or `testing` mode.
E.g.: ``https://<examplePublicKey>@o<something>.ingest.sentry.io/<project-Id>``

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


.. _monitoring

Monitoring
-----------

Monitoring potential problems in FlexMeasure's operations.


SENTRY_DSN
^^^^^^^^^^^^

Set tokenized URL, so errors will be sent to Sentry when ``app.env`` is not in `debug` or `testing` mode.
E.g.: ``https://<examplePublicKey>@o<something>.ingest.sentry.io/<project-Id>``

Default: ``None``


FLEXMEASURES_SENTRY_CONFIG
^^^^^^^^^^^^^^^^^^^^^^^^^^^

A dictionary with values to configure reporting to Sentry. Some options are taken care of by FlexMeasures (e.g. environment and release), but not all.
See `here <https://docs.sentry.io/platforms/python/configuration/options/>_` for a complete list.

Default: ``{}``


FLEXMEASURES_TASK_CHECK_AUTH_TOKEN
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Token which external services can use to check on the status of recurring tasks within FlexMeasures.

Default: ``None``


.. _monitoring_mail_recipients:

FLEXMEASURES_MONITORING_MAIL_RECIPIENTS
^^^^^^^^^^^^^^^^^^^^^^^

E-mail addresses to send monitoring alerts to from the CLI task ``flexmeasures monitor tasks``. For example ``["fred@one.com", "wilma@two.com"]``

Default: ``[]``


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
so that old imported data can be demoed as if it were current.

Default: ``None``
