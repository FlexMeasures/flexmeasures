.. _security:

Security aspects
====================================

Data
-------

There are two types of data on FlexMeasures servers - files (e.g. source code, images) and data in a database (e.g. user data and time series for energy consumption/generation or weather).

* Files are stored on EBS volumes on Amazon Web Services. These are shared with other customers of Amazon, but protected from them by Linux's chroot system -- each user can see only the files in their own section of the disk.

* Database data is stored in PostgresDB instances which are not shared with other Amazon customers. They are password-protected.

* Finally, The application communicates all data with HTTPS, the Hypertext Transfer Protocol encrypted by Transport Layer Security. This is used even if the application is accessed via ``http://``.


.. _authentication:

Authentication 
----------------

*Authentication* is the system by which users tell the FlexMeasures platform that they are who they claim they are.
This involves a username/password combination ("credentials") or an access token.

* No user passwords are stored in clear text on any server - the FlexMeasures platform only stores the hashed passwords (encrypted with the `bcrypt hashing algorithm <https://passlib.readthedocs.io/en/stable/lib/passlib.hash.bcrypt.html>`_). If an attacker steals these password hashes, they cannot compute the passwords from them in a practical amount of time.
* Access tokens are used so that the sending of usernames and passwords is limited (even if they are encrypted via https, see above) when dealing with the part of the FlexMeasures platform which sees the most traffic: the API functionality. Tokens thus have use cases for some scenarios, where developers want to treat authentication information with a little less care than credentials should be treated with, e.g. sharing among computers. However, they also expire fast, which is a common industry practice (by making them short-lived and requiring refresh, FlexMeasures limits the time an attacker can abuse a stolen token). At the moment, the access tokens on FlexMeasures platform expire after six hours. Access tokens are encrypted and validated with the `sha256_crypt algorithm <https://passlib.readthedocs.io/en/stable/lib/passlib.hash.sha256_crypt.html>`_, and `the functionality to expire tokens is realised by storing the seconds since January 1, 2011 in the token <https://pythonhosted.org/itsdangerous/#itsdangerous.TimestampSigner>`_. The maximum age of access tokens in FlexMeasures can be altered by setting the env variable `SECURITY_TOKEN_MAX_AGE` to the number of seconds after which tokens should expire.


.. note:: Authentication (and authorization, see below) affects the FlexMeasures API and UI. The CLI (command line interface) can only be used if the user is already on the server and can execute ``flexmeasures`` commands, thus we can safely assume they are admins.


.. _authorization:

Authorization
--------------

*Authorization* is the system by which the FlexMeasures platform decides whether an authenticated user can access data. Data about users and assets. Or metering data, forecasts and schedules.

For instance, a user is authorized to update his or her personal data, like the surname. Other users should not be authorized to do that. We can also authorize users to do something because they belong to a certain account. An example for this is to read the meter data of the account's assets. Any regular user should *only* be able to read data that their account should be able to see.

.. note:: Each user belongs to exactly one account.

In a nutshell, the way FlexMeasures implements authorization works as follows: The data models codify under which conditions a user can have certain permissions to work with their data. Permissions allow distinct ways of access like reading, writing or deleting. The API endpoints are where we know what needs to happen to what data, so there we make sure that the user has the necessary permissions.

We already discussed certain conditions under which a user has access to data ― being a certain user or belonging to a specific account. Furthermore, authorization conditions can also be implemented via *roles*: 

* ``Account roles`` are often used for authorization. We support several roles which are mentioned in the USEF framework but more roles are possible (e.g. defined by custom-made services, see below). For example, a user might be authorized to write sensor data if they belong to an account with the "MDC" account role ("MDC" being short for meter data company).
* ``User roles`` give a user personal authorizations. For instance, we have a few `admin`\ s who can perform all actions, and `admin-reader`\ s who can read everything. Other roles have only an effect within the user's account, e.g. there could be an "HR" role which allows to edit user data like surnames within the account.
* Roles cannot be edited via the UI at the moment. They are decided when a user or account is created in the CLI (for adding roles later, we use the database for now). Editing roles in UI and CLI is future work.


.. note:: Custom energy flexibility services developed on top of FlexMeasures also need to implement authorization. More on this in :ref:`auth-dev`. Here is an example for a custom authorization concept: services can use account roles to achieve their custom authorization. E.g. if several services run on one FlexMeasures server, each service could define a "MyService-subscriber" account role, to make sure that only users of such accounts can use the endpoints.