.. _security:

Security aspects
====================================

Data
-------

There are two types of data on FlexMeasures servers - files (e.g. source code, images) and data in a database (e.g. user
data and time series for energy consumption/generation or weather).

* Files are stored on EBS volumes on Amazon Web Services. These are shared with other customers of Amazon, but protected from them by Linux's chroot system -- each user can see only the files in their own section of the disk.

* Database data is stored in PostgresDB instances which are not shared with other Amazon customers. They are password-protected.

* Finally, The application communicates all data with HTTPS, the Hypertext Transfer Protocol encrypted by Transport Layer Security. This is used even if the application is accessed via `http://`.


.. _auth:

Authentication and Authorisation
---------------------------------

*Authentication* is the system by which users tell the FlexMeasures platform that they are who they claim they are.
This involves a username/password combination ("credentials") or an access token.

* No user passwords are stored in clear text on any server - the FlexMeasures platform only stores the hashed passwords (encrypted with the `bcrypt hashing algorithm <https://passlib.readthedocs.io/en/stable/lib/passlib.hash.bcrypt.html>`_). If an attacker steals these password hashes, they cannot compute the passwords from them in a practical amount of time.
* Access tokens are used so that the sending of usernames and passwords is limited (even if they are encrypted via https, see above) when dealing with the part of the FlexMeasures platform which sees the most traffic: the API functionality. Tokens thus have use cases for some scenarios, where developers want to treat authentication information with a little less care than credentials should be treated with, e.g. sharing among computers. However, they also expire fast, which is a common industry practice (by making them short-lived and requiring refresh, FlexMeasures limits the time an attacker can abuse a stolen token). At the moment, the access tokens on FlexMeasures platform expire after six hours. Access tokens are encrypted and validated with the `sha256_crypt algorithm <https://passlib.readthedocs.io/en/stable/lib/passlib.hash.sha256_crypt.html>`_, and `the functionality to expire tokens is realised by storing the seconds since January 1, 2011 in the token <https://pythonhosted.org/itsdangerous/#itsdangerous.TimestampSigner>`_. The maximum age of access tokens in FlexMeasures can be altered by setting the env variable `SECURITY_TOKEN_MAX_AGE` to the number of seconds after which tokens should expire.

*Authorisation* is the system by which the FlexMeasures platform decides whether an authenticated user can access a feature. For instance, many features are reserved for administrators, others for Prosumers (the owner of assets).

* This is achieved via *roles*. Each user has at least one role, but could have several, as well.
* Roles cannot be edited via the UI at the moment. They are decided when a user is created.
