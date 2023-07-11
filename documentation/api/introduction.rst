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
     'versions': ['v3_0']
    }

So this tells us which API versions exist. For instance, we know that the latest API version is available at:

.. code-block:: html

    https://company.flexmeasures.io/api/v3_0


Also, we can see that a list of endpoints is available on https://flexmeasures.readthedocs.io for each of these versions.

.. note:: Sunset API versions are still documented there, simply select an older version.


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

.. note:: Each access token has a limited lifetime, see :ref:`api_auth`.

.. _api_deprecation:

Deprecation and sunset
----------------------

When an API feature becomes obsolete, we deprecate it.
Deprecation of major features doesn't happen a lot, but when it does, it happens in multiple stages, during which we support clients and hosts in adapting.
For more information on our multi-stage deprecation approach and available options for FlexMeasures hosts, see :ref:`Deprecation and sunset for hosts<api_deprecation_hosts>`.

.. _api_deprecation_clients:

Clients
^^^^^^^

Professional API users should monitor API responses for the ``"Deprecation"`` and ``"Sunset"`` response headers [see `draft-ietf-httpapi-deprecation-header-02 <https://datatracker.ietf.org/doc/draft-ietf-httpapi-deprecation-header/>`_ and `RFC 8594 <https://www.rfc-editor.org/rfc/rfc8594>`_, respectively], so system administrators can be warned when using API endpoints that are flagged for deprecation and/or are likely to become unresponsive in the future.

The deprecation header field shows an `IMF-fixdate <https://www.rfc-editor.org/rfc/rfc7231#section-7.1.1.1>`_ indicating when the API endpoint was deprecated.
The sunset header field shows an `IMF-fixdate <https://www.rfc-editor.org/rfc/rfc7231#section-7.1.1.1>`_ indicating when the API endpoint is likely to become unresponsive.

More information about a deprecation, sunset, and possibly recommended replacements, can be found under the ``"Link"`` response header. Relevant relations are:

- ``"deprecation"``
- ``"successor-version"``
- ``"latest-version"``
- ``"alternate"``
- ``"sunset"``

Here is a client-side code example in Python (this merely prints out the deprecation header, sunset header and relevant links, and should be revised to make use of the client's monitoring tools):

.. code-block:: python

        def check_deprecation_and_sunset(self, url, response):
        """Print deprecation and sunset headers, along with info links.

        Reference
        ---------
        https://flexmeasures.readthedocs.io/en/latest/api/introduction.html#deprecation-and-sunset
        """
        # Go through the response headers in their given order
        for header, content in response.headers:
            if header == "Deprecation":
                print(f"Your request to {url} returned a deprecation warning. Deprecation: {content}")
            elif header == "Sunset":
                print(f"Your request to {url} returned a sunset warning. Sunset: {content}")
            elif header == "Link" and ('rel="deprecation";' in content or 'rel="sunset";' in content):
                print(f"Further info is available: {content}")

.. _api_deprecation_hosts:

Hosts
^^^^^

FlexMeasures versions go through the following stages for deprecating major features (such as API versions):

- :ref:`api_deprecation_stage_1`: status 200 (OK) with :ref:`relevant headers<api_deprecation_clients>`, plus a toggle to 410 (Gone) for blackout tests
- :ref:`api_deprecation_stage_2`: status 410 (Gone), plus a toggle to 200 (OK) for sunset rollbacks
- :ref:`api_deprecation_stage_3`: status 410 (Gone)

Let's go over these stages in more detail.

.. _api_deprecation_stage_1:

Stage 1: Deprecation
""""""""""""""""""""

When upgrading to a FlexMeasures version that deprecates an API version (e.g. ``flexmeasures==0.12`` deprecates API version 2), clients will receive ``"Deprecation"`` and ``"Sunset"`` response headers [see `draft-ietf-httpapi-deprecation-header-02 <https://datatracker.ietf.org/doc/draft-ietf-httpapi-deprecation-header/>`_ and `RFC 8594 <https://www.rfc-editor.org/rfc/rfc8594>`_, respectively].

Hosts should not expect every client to monitor response headers and proactively upgrade to newer API versions.
Please make sure that your users have upgraded before you upgrade to a FlexMeasures version that sunsets an API version.
You can do this by checking your server logs for warnings about users who are still calling deprecated endpoints.

In addition, we recommend running blackout tests during the deprecation notice phase.
You (and your users) can learn which systems need attention and how to deal with them.
Be sure to announce these beforehand.
Here is an example of how to run a blackout test:
If a sunset happens in version ``0.13``, and you are hosting a version which includes the deprecation notice (e.g. ``0.12``), FlexMeasures will simulate the sunset if you set the config setting ``FLEXMEASURES_API_SUNSET_ACTIVE = True`` (see :ref:`Sunset Configuration<sunset-config>`).
During such a blackout test, clients will receive ``HTTP status 410 (Gone)`` responses when calling corresponding endpoints.

.. admonition:: What is a blackout test
   :class: info-icon

   A blackout test is a planned, timeboxed event when a host will turn off a certain API or some of the API capabilities.
   The test is meant to help developers understand the impact the retirement will have on the applications and users.
   `Source: Platform of Trust <https://design.oftrust.net/api-migration-policies/blackout-testing>`_

.. _api_deprecation_stage_2:

Stage 2: Preliminary sunset
"""""""""""""""""""""""""""

When upgrading to a FlexMeasures version that sunsets an API version (e.g. ``flexmeasures==0.13`` sunsets API version 2), clients will receive ``HTTP status 410 (Gone)`` responses when calling corresponding endpoints.

In case you have users that haven't upgraded yet, and would still like to upgrade FlexMeasures (to the version that officially sunsets the API version), you can.
For a little while after sunset (usually one more minor version), we will continue to support a "sunset rollback".
To enable this, just set the config setting ``FLEXMEASURES_API_SUNSET_ACTIVE = False`` and consider announcing some more blackout tests to your users, during which you can set this setting to ``True`` to reactivate the sunset.

.. _api_deprecation_stage_3:

Stage 3: Definitive sunset
""""""""""""""""""""""""""

After upgrading to one of the next FlexMeasures versions (e.g. ``flexmeasures==0.14``), clients that call sunset endpoints will receive ``HTTP status 410 (Gone)`` responses.
