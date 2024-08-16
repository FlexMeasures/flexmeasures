.. _configuration:

Configuration
=============

The following configurations are used by FlexMeasures.

Required settings (e.g. postgres db) are marked with a double star (**).
To enable easier quickstart tutorials, continuous integration use cases and basic usage of FlexMeasures within other projects, these required settings, as well as a few others, can be set by environment variables ― this is also noted per setting.
Recommended settings (e.g. mail, redis) are marked by one star (*).

.. note:: FlexMeasures is best configured via a config file. The config file for FlexMeasures can be placed in one of two locations: 


* in the user's home directory (e.g. ``~/.flexmeasures.cfg`` on Unix). In this case, note the dot at the beginning of the filename!
* in the app's instance directory (e.g. ``/path/to/your/flexmeasures/code/instance/flexmeasures.cfg``\ ). The path to that instance directory is shown to you by running flexmeasures (e.g. ``flexmeasures run``\ ) with required settings missing or otherwise by running ``flexmeasures shell``. Under :ref:`docker_configuration`, we explain how to load a config file into a FlexMeasures Docker container.


Basic functionality
-------------------

LOGGING_LEVEL
^^^^^^^^^^^^^

Level above which log messages are added to the log file. See the ``logging`` package in the Python standard library.

Default: ``logging.WARNING``

.. note:: This setting is also recognized as environment variable.


.. _modes-config:

FLEXMEASURES_MODE
^^^^^^^^^^^^^^^^^

The mode in which FlexMeasures is being run, e.g. "demo" or "play".
This is used to turn on certain extra behaviours, see :ref:`modes-dev` for details.

Default: ``""``


.. _overwrite-config:

FLEXMEASURES_ALLOW_DATA_OVERWRITE
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Whether to allow overwriting existing data when saving data to the database.

Default: ``False``


.. _solver-config:

FLEXMEASURES_LP_SOLVER
^^^^^^^^^^^^^^^^^^^^^^

The command to run the scheduling solver. This is the executable command which FlexMeasures calls via the `pyomo library <http://www.pyomo.org/>`_. Potential values might be ``cbc``, ``cplex``, ``glpk`` or ``appsi_highs``. Consult `their documentation <https://pyomo.readthedocs.io/en/stable/solving_pyomo_models.html#supported-solvers>`_ to learn more. 
We have tested FlexMeasures with `HiGHS <https://highs.dev/>`_ and `Cbc <https://coin-or.github.io/Cbc/intro>`_.
Note that you need to install the solver, read more at :ref:`installing-a-solver`.

Default: ``"appsi_highs"``



FLEXMEASURES_HOSTS_AND_AUTH_START
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Configuration used for entity addressing. This contains the domain on which FlexMeasures runs
and the first month when the domain was under the current owner's administration.

Default: ``{"flexmeasures.io": "2021-01"}``


.. _plugin-config:

FLEXMEASURES_PLUGINS
^^^^^^^^^^^^^^^^^^^^^^^^^

A list of plugins you want FlexMeasures to load (e.g. for custom views or CLI functions). 
This can be a Python list (e.g. ``["plugin1", "plugin2"]``) or a comma-separated string (e.g. ``"plugin1, plugin2"``).

Two types of entries are possible here:

* File paths (absolute or relative) to plugins. Each such path needs to point to a folder, which should contain an ``__init__.py`` file where the Blueprint is defined. 
* Names of installed Python modules. 

Added functionality in plugins needs to be based on Flask Blueprints. See :ref:`plugins` for more information and examples.

Default: ``[]``

.. note:: This setting is also recognized as environment variable (since v0.14, which is also the version required to pass this setting as a string).


FLEXMEASURES_DB_BACKUP_PATH
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Relative path to the folder where database backups are stored if that feature is being used.

Default: ``"migrations/dumps"``

FLEXMEASURES_PROFILE_REQUESTS
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If True, the processing time of requests are profiled.

The overall time used by requests are logged to the console. In addition, if `pyinstrument` is installed, then a profiling report is made (of time being spent in different function calls) for all Flask API endpoints.

The profiling results are stored in the ``profile_reports`` folder in the instance directory.

Note: Profile reports for API endpoints are overwritten on repetition of the same request.

Interesting for developers.

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

Default: ``""``


.. _extra-css-config:

FLEXMEASURES_EXTRA_CSS_PATH
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A URL path to identify a CSS style-sheet to be added to the base template.
The path can be a complete URL or a relative from the app root. 

.. note:: You can also add extra styles for plugins with the usual Blueprint method. That is more elegant but only applies to the Blueprint's views.

Default: ``""``


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

Default: ``["dashboard"]``


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


FLEXMEASURES_ASSET_TYPE_GROUPS
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

How to group asset types together, e.g. in a dashboard.

Default: ``{"renewables": ["solar", "wind"], "EVSE": ["one-way_evse", "two-way_evse"]}``

FLEXMEASURES_JS_VERSIONS
^^^^^^^^^^^^^^^^^^^^^^^^

Default: ``{"vega": "5.22.1", "vegaembed": "6.20.8", "vegalite": "5.2.0"}``


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

Time to live for schedule UUIDs of successful scheduling jobs. Set a negative timedelta to persist forever.

Default: ``timedelta(days=7)``

FLEXMEASURES_JOB_CACHE_TTL
^^^^^^^^^^^^^^^^^^^^^^^^^^

Time to live for the job caching keys in seconds. The default value of 1h responds to the reality that within an hour, there is not
much change, other than the input arguments, that justifies recomputing the schedules.

In an hour, we will have more accurate forecasts available and the situation of the power grid
might have changed (imbalance prices, distribution level congestion, activation of FCR or aFRR reserves, ...).

Set a negative value to persist forever.

.. warning::
    Keep in mind that unless a proper clean up mechanism is set up, the number of
    caching keys will grow with time if the TTL is set to a negative value.

Default: ``3600``

.. _datasource_config:

FLEXMEASURES_DEFAULT_DATASOURCE
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The default DataSource of the resulting data from `DataGeneration` classes.

Default: ``"FlexMeasures"``


.. _planning_horizon_config:

FLEXMEASURES_PLANNING_HORIZON
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The default horizon for making schedules.
API users can set a custom duration if they need to.

Default: ``timedelta(days=2)``


FLEXMEASURES_MAX_PLANNING_HORIZON
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The maximum horizon for making schedules.
API users are not able to request longer schedules.
Can be set to a specific ``datetime.timedelta`` or to an integer number of planning steps, where the duration of a planning step is equal to the resolution of the applicable power sensor.
Set to ``None`` to forgo this limitation altoghether.

Default: ``2520`` (e.g. 7 days for a 4-minute resolution sensor, 105 days for a 1-hour resolution sensor)


Access Tokens
---------------

.. _mapbox_access_token:

MAPBOX_ACCESS_TOKEN
^^^^^^^^^^^^^^^^^^^

Token for accessing the MapBox API (for displaying maps on the dashboard and asset pages). You can learn how to obtain one `here <https://docs.mapbox.com/help/glossary/access-token/>`_

Default: ``None``

.. note:: This setting is also recognized as environment variable.

.. _sentry_access_token:

SENTRY_SDN
^^^^^^^^^^^^

Set tokenized URL, so errors will be sent to Sentry when ``app.env`` is not in `debug` or `testing` mode.
E.g.: ``https://<examplePublicKey>@o<something>.ingest.sentry.io/<project-Id>``

Default: ``None``

.. note:: This setting is also recognized as environment variable.


SQLAlchemy
----------

This is only a selection of the most important settings.
See `the Flask-SQLAlchemy Docs <https://flask-sqlalchemy.palletsprojects.com/en/master/config>`_ for all possibilities.

SQLALCHEMY_DATABASE_URI (**)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Connection string to the postgres database, format: ``postgresql://<user>:<password>@<host-address>[:<port>]/<db>``

Default: ``None``

.. note:: This setting is also recognized as environment variable.


SQLALCHEMY_ENGINE_OPTIONS
^^^^^^^^^^^^^^^^^^^^^^^^^

Configuration of the SQLAlchemy engine.

Default: 

.. code-block:: python

       {
           "pool_recycle": 299,
           "pool_pre_ping": True,
           "connect_args": {"options": "-c timezone=utc"},
       }


SQLALCHEMY_TEST_DATABASE_URI
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When running tests (``make test``, which runs ``pytest``), the default database URI is set in ``utils.config_defaults.TestingConfig``.
You can use this setting to overwrite that URI and point the tests to an (empty) database of your choice. 

.. note:: This setting is only supported as an environment variable, not in a config file, and only during testing.



Security
--------

Settings to ensure secure handling of credentials and data.

For Flask-Security and Flask-Cors (setting names start with "SECURITY" or "CORS"), this is only a selection of the most important settings.
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


FLEXMEASURES_FORCE_HTTPS
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Set to ``True`` if all requests should be forced to be HTTPS.

Default: ``False``


FLEXMEASURES_ENFORCE_SECURE_CONTENT_POLICY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When ``FLEXMEASURES_ENFORCE_SECURE_CONTENT_POLICY`` is set to ``True``, the ``<meta>`` tag with the ``Content-Security-Policy`` directive, specifically ``upgrade-insecure-requests``, is included in the HTML head. This directive instructs the browser to upgrade insecure requests from ``http`` to ``https``. One example of a use case for this is if you have a load balancer in front of FlexMeasures, which is secured with a certificate and only accepts https.

Default: ``False``


.. _mail-config:

Mail
----

For FlexMeasures to be able to send email to users (e.g. for resetting passwords), you need an email account which can do that (e.g. GMail).

This is only a selection of the most important settings.
See `the Flask-Mail Docs <https://flask-mail.readthedocs.io/en/latest/#configuring-flask-mail>`_ for others.

.. note:: The mail settings are also recognized as environment variables.

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

.. note:: Some recipient mail servers will refuse emails for which the shown email address (set under ``MAIL_DEFAULT_SENDER``) differs from the sender's real email address (registered to ``MAIL_USERNAME``).
         Match them to avoid ``SMTPRecipientsRefused`` errors.

Default:

.. code-block:: python

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

.. note:: The redis settings are also recognized as environment variables.


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

.. _sunset-config:

Sunset
------

FLEXMEASURES_API_SUNSET_ACTIVE
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Allow control over the effect of sunsetting API versions.
Specifically, if True, the endpoints of sunset API versions will return ``HTTP status 410 (Gone)`` status codes.
If False, these endpoints will either return ``HTTP status 410 (Gone) status codes``, or work like before (including Deprecation and Sunset headers in their response), depending on whether the installed FlexMeasures version still contains the endpoint implementations.

Default: ``False``

FLEXMEASURES_API_SUNSET_DATE
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Allow to override the default sunset date for your clients.

Default: ``None`` (defaults are set internally for each sunset API version, e.g. ``"2023-05-01"`` for v2.0)

FLEXMEASURES_API_SUNSET_LINK
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Allow to override the default sunset link for your clients.

Default: ``None`` (defaults are set internally for each sunset API version, e.g. ``"https://flexmeasures.readthedocs.io/en/v0.13.0/api/v2_0.html"`` for v2.0)

FLEXMEASURES_HIDE_FLEXCONTEXT_EDIT
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Hide the part of the asset form which lets one edit flex context sensors. 
Why? Loading the page can take long when the number of sensors is very high (e.g. due to many KPIs being reported).
This is a temporary solution for this problem until a better design is made.

Default: ``False``