.. _api_introduction:

API Introduction
============

This document details the Application Programming Interface (API) of the FlexMeasures web service. The API supports user automation for flexibility valorisation in the energy sector, both in a live setting and for the purpose of simulating scenarios. The web service adheres to the concepts and terminology used in the Universal Smart Energy Framework (USEF).

All requests and responses to and from the web service should be valid JSON messages.
For deeper explanations on how to construct messages, see :ref:`api_notation`.

.. _api_versions:

Main endpoint and API versions
------------------------------

All versions of the API are released on:

.. code-block:: html

    https://<flexmeasures-root-url>/api

So if you are running FlexMeasures on your computer, it would be:

.. code-block:: html

    https://localhost:5000/api

Let's assume we are running a server for a client at:

.. code-block:: html

    https://company.flexmeasures.io/api

where `company` is a client of ours. All their accounts' data lives on that server.

We assume in this document that the FlexMeasures instance you want to connect to is hosted at https://company.flexmeasures.io.

Let's see what the ``/api`` endpoint returns:

.. code-block:: python

    >>> import requests
    >>> res = requests.get("https://company.flexmeasures.io/api")
    >>> res.json()
    {'flexmeasures_version': '0.9.0',
     'message': 'For these API versions endpoints are available. An authentication token can be requested at: /api/requestAuthToken. For a list of services, see https://flexmeasures.readthedocs.io',
     'status': 200,
     'versions': ['v1', 'v1_1', 'v1_2', 'v1_3', 'v2_0', 'v3_0']
    }

So this tells us which API versions exist. For instance, we know that the latest API version is available at:

.. code-block:: html

    https://company.flexmeasures.io/api/v3_0


Also, we can see that a list of endpoints is available on https://flexmeasures.readthedocs.io for each of these versions.

.. _api_auth:

Authentication
--------------

Service usage is only possible with a user access token specified in the request header, for example:

.. code-block:: json

    {
        "Authorization": "<token>"
    }

A fresh "<token>" can be generated on the user's profile after logging in:

.. code-block:: html

    https://company.flexmeasures.io/logged-in-user

or through a POST request to the following endpoint:

.. code-block:: html

    https://company.flexmeasures.io/api/requestAuthToken

using the following JSON message for the POST request data:

.. code-block:: json

    {
        "email": "<user email>",
        "password": "<user password>"
    }

which gives a response like this if the credentials are correct:

.. code-block:: json

    {
        "auth_token": "<authentication token>",
        "user_id": "<ID of the user>"
    }

.. note:: Each access token has a limited lifetime, see :ref:`auth`.
