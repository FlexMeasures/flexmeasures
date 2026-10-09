.. _security:

Security aspects
====================================

This page explains how security is handled in FlexMeasures. This deals with encryption, authentication and authorization.
For hosts, we also provide some best practices.

.. contents::
    :local:
    :depth: 1


Data
-------

A FlexMeasures server handles two types of data in its Postgres database - structural data (e.g. information about sites, assets, users) and time series data for energy consumption/generation, prices or weather. Read more on :ref:`datamodel`. There is also a Redis database with information about ongoing forecasting and scheduling jobs (stored in a queueing system).

How these Postgres and Redis databases are set up and protected is up to the host. 

More crucial to this documentation is that each FlexMeasures server reads from and writes to the Postgres database according to strict authentication and authorization rules. Much of the remainder of this page describes how this is implemented.

Finally, when sending data back and forth between clients (e.g. browsers) and the server, the FlexMeasures application communicates all data with HTTPS, the Hypertext Transfer Protocol encrypted by Transport Layer Security. This is used even if the application is accessed via ``http://``.


.. _authentication:


Authentication 
----------------

*Authentication* is the system by which users tell the FlexMeasures platform that they are who they claim they are.
This involves a username/password combination ("credentials") or an access token.

* No user passwords are stored in clear text on any server - the FlexMeasures platform only stores the hashed passwords (encrypted with the `bcrypt hashing algorithm <https://passlib.readthedocs.io/en/stable/lib/passlib.hash.bcrypt.html>`_). If an attacker steals these password hashes, they cannot compute the passwords from them in a practical amount of time.
* In the API, access tokens are used so that the sending of usernames and passwords is limited (even if they are encrypted via https, see above) when dealing with the part of the FlexMeasures platform which sees the most traffic: the API functionality. Tokens thus have use cases for some scenarios, where developers want to treat authentication information with a little less care than credentials should be treated with, e.g. sharing among computers. However, they also expire fast, which is a common industry practice (by making them short-lived and requiring refresh, FlexMeasures limits the time an attacker can abuse a stolen token). At the moment, the access tokens on FlexMeasures platform expire after six hours. Access tokens are encrypted and validated with the `sha256_crypt algorithm <https://passlib.readthedocs.io/en/stable/lib/passlib.hash.sha256_crypt.html>`_, and `the functionality to expire tokens is realised by storing the seconds since January 1, 2011 in the token <https://pythonhosted.org/itsdangerous/#itsdangerous.TimestampSigner>`_. The maximum age of access tokens in FlexMeasures can be altered by setting the env variable `SECURITY_TOKEN_MAX_AGE` to the number of seconds after which tokens should expire.
* In the UI, FlexMeasures uses two-factor authentication (2FA). This means that the knowledge of the password to your FlexMeasures account is not sufficient to gain access ― you also need a second piece of knowledge, which requires you to also have access to an independent system or device (e.g. a token sent to your email address).

.. note:: Authentication (and authorization, see below) affects the FlexMeasures API and UI. The CLI (command line interface) can only be used if the user is already on the server and can execute ``flexmeasures`` commands, thus we can safely assume they are admins.


.. _authorization:

Authorization
--------------

*Authorization* is the system by which the FlexMeasures platform decides whether an authenticated user can access data. Data about users and assets. Or metering data, forecasts and schedules.

For instance, a user is authorized to update his or her personal data, like the surname. Other users should not be authorized to do that. We can also authorize users to do something because they belong to a certain account. An example for this is to read the meter data of the account's assets. Any regular user should *only* be able to read data that their account should be able to see.

.. note:: Each user belongs to exactly one account.

Authorization requires both a named permission granted by an eligible user role and access to the particular resource. Built-in role grants are listed explicitly in ``flexmeasures.auth.policy``; adding a permission does not automatically grant it to existing roles. The ``Role.permissions`` property reads these grants from code; they are not stored on each role in the database. Each model's ``__acl__`` method defines the principals for named actions, such as ``trigger-schedules`` or ``manage-users``. API and UI endpoints check the permission for their resource before carrying out an action.

For example, ``trigger-schedules`` is the same identifier in a role's grants, an asset's ACL and the endpoint's check. An account member with that grant can trigger schedules only where the asset ACL also matches their home account. The names for these permissions are defined in ``flexmeasures.auth.policy``; ``read``, ``post-data``, ``trigger-schedules``, ``edit-assets`` and ``manage-users`` are examples. The older ``create-children``, ``update`` and ``delete`` names remain available for custom ACLs during the transition. Their entries on built-in resources preserve existing callers; named actions define the primary rules. "Children" refers to the hierarchy of assets, sensors and beliefs described in :ref:`datamodel`; assets can have other assets as children.


User and Account Roles
^^^^^^^^^^^^^^^^^^^^^^^

We already discussed certain conditions under which a user has access to data ― being a certain user or belonging to a specific account. Furthermore, authorization conditions can also be implemented via *roles*: 

* ``Account roles`` are often used for authorization. They are extensible: hosts and custom services can define their own roles. In the core FlexMeasures codebase, the ``Consultancy`` account role currently has built-in authorization behavior: together with the user role ``consultant``, it allows consultancy accounts to create client accounts and access consultancy-related data.
* ``User roles`` grant named permissions. ``admin`` can perform all actions and ``admin-reader`` can read everything. Home roles apply within the user's own account. The ``consultant`` role applies through consultancy access to client accounts.

We look into supported user roles in more detail below.

Roles are not a closed built-in list. Some are hardcoded in the core authorization model, while others are installation-specific. Both Account and User's roles can be managed through the account UI and API.


.. note:: Custom energy flexibility services which are developed on top of FlexMeasures can also add their own kind of authorization, at least for the endpoints they define - using roles.
          More on this in :ref:`auth-dev`. An example for a custom authorization concept is that services can use account roles to achieve their custom authorization.
          E.g. if several services run on one FlexMeasures server, each service could define a "MyService-subscriber" account role, to make sure that only users of such accounts can use the endpoints.
          Developers are also free to add their own user roles and check on those in their custom code.


Supported User Roles
^^^^^^^^^^^^^^^^^^^^^

These roles are natively supported, in the order used by the user role editor (which does not offer ``admin``). Each comparison describes what the next role adds **when assigned alongside the earlier roles**. Roles do not inherit from the preceding role: ``consultant`` acts on linked client accounts, and ``admin-reader`` adds site-wide reading rather than client-account write access.

- ``account-reader``: Read resources in the home account. This is the smallest built-in grant and, by itself, cannot initiate a password reset. An account administrator or consultant can initiate one for the user.
- ``account-data-integrator``: Adds posting data and resetting one's own password to home-account reading.
- ``account-member``: Adds regular work with home-account resources, including editing assets and triggering jobs.
- ``account-admin``: Adds management of users and deletion of data in the home account.
- ``consultant``: Adds access to linked client accounts through the consultancy relationship (of the home account), including management actions there. On its own, it grants no home-account access. More on this below.
- ``admin-reader``: Extends reading to every account on the site. On its own, it grants read access only.
- ``admin``: Extends all actions to every account on the site.

Roles grant additional permissions; assigning ``account-reader`` or ``account-data-integrator`` does not take away permissions from other roles. To convert an existing user to either role, remove ``account-member`` and other broader roles from that user. The database upgrade assigns ``account-member`` to all existing users so that their previous implicit account access is preserved, and creates the ``account-reader`` and ``account-data-integrator`` role rows. New users receive ``account-member`` by default unless a different set of roles is specified.


Consultancy
^^^^^^^^^^^

A special case of authorization is consultancy: a consultancy account can read data from other accounts (usually their clients, which is handy for servicing them).
For this, accounts have an attribute called ``consultancy_account_id``. Users in the consultancy account with the user role ``consultant`` can read data in their client accounts.

In addition, consultants can create/edit client accounts through the API and UI, when their own account has the Consultancy account role. When they create a client account, it is automatically linked to the consultancy account as client account.

Setting or changing ``consultancy_account_id`` arbitrarily remains an admin capability. Admins can do this via the ``/accounts`` PATCH endpoint and in the UI.

.. _security-best-practices-for-hosts:

Best security-practices for hosts
-----------------------------

* Use the ``TRUSTED_HOSTS`` setting (see the Flask docs on `the configuration <https://flask.palletsprojects.com/en/stable/config/#TRUSTED_HOSTS>`_ and on `the topic of host header validation <https://flask.palletsprojects.com/en/stable/web-security/#host-header-validation>`_) to specify on which hosts the platform is actually being provided.
  As an example for why this is valuable: FlexMeasures constructs URLs, e.g. for password reset links. Client code could set its own ``Host`` request header to make these URLs lead to a different server.
  If the client "poisons" the URLs for its own users this way, they are using the user's trust in the FlexMeasures host platform to hack them.
  List your own domain in this setting, but also the IP of your load balancer, if you are using one.
