.. _api_introduction:

API Introduction
================

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

    http://localhost:5000/api

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

All API responses include a ``FlexMeasures-Version`` header with the current server version, and responses from versioned API endpoints (e.g. under ``/api/v3_0``) also include an ``API-Version`` header indicating the API version:

.. code-block:: http

    HTTP/1.1 200 OK
    FlexMeasures-Version: 0.32.0
    API-Version: v3_0


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

Access tokens expire after six hours by default; the host can configure a different lifetime.
The existing request and response above remain unchanged. Authenticate again with your
email and password when the token expires, or opt in to refresh tokens as described below.
Use the token directly in the ``Authorization`` header, without a ``Bearer`` prefix.

.. _api_refresh_tokens:

Refresh tokens
^^^^^^^^^^^^^^

A refresh token lets an integration obtain a new access token without sending the user's
password again. It is a long-lived credential: protect it as carefully as a password.
These JSON endpoints extend FlexMeasures authentication; they are not an OAuth implementation
and do not change browser login sessions.

To opt in, add ``"include-refresh-token": true`` to ``POST /api/requestAuthToken``:

.. code-block:: json

    {
        "email": "user@example.com",
        "password": "<user password>",
        "include-refresh-token": true
    }

A successful response has HTTP status 200:

.. code-block:: json

    {
        "auth_token": "<access token>",
        "user_id": 1,
        "refresh-token": "<refresh token>",
        "expires-in": 21600
    }

``auth_token`` is the access token used for ordinary API requests. ``expires-in`` is its
lifetime in seconds, reflecting the host's configuration. The example uses the default
six hours. A refresh token cannot authenticate an ordinary API request.
If the host has configured access tokens without an expiry, ``expires-in`` is ``null``.
Responses also include FlexMeasures' usual ``status`` field.

To replace the access token, send ``POST /api/refreshAuthToken`` with this JSON body:

.. code-block:: json

    {"refresh-token": "<current refresh token>"}

No password or access token is required, so refresh also works after the access token
expires. A successful refresh returns the same four fields as the opt-in login response,
including a replacement refresh token. Save both replacement tokens together before making
another refresh request.

Each refresh token can be used only once. All replacement tokens descended from a login
form a *token family*. Reusing an already exchanged token revokes that family, including
its newest refresh token. Serialize refresh requests across workers that share credentials.
If a refresh response is lost, authenticate again with email and password; blindly retrying
the old token may revoke the family.

To stop future refreshes, send ``POST /api/revokeRefreshToken`` with the current refresh
token in the same JSON format. It returns HTTP status 200 with ``{"revoked": true}``
and revokes the family. Already issued access tokens remain usable until they expire or
are invalidated, for example by a password change. Disabled users cannot authenticate.
Password changes and user deactivation revoke existing refresh-token families.
Reactivating a user does not restore those families. Revocation does not log out
an existing browser session.

By default, a refresh-token family expires 90 days after its initial login, or after
7 days without a successful refresh, whichever happens first. Rotation does not extend
the absolute lifetime. Hosts configure these limits with ``SECURITY_REFRESH_TOKEN_MAX_AGE``
and ``SECURITY_REFRESH_TOKEN_MAX_IDLE``. After expiry or revocation, authenticate again
with email and password.
These settings take Python ``datetime.timedelta`` values. API refresh support does not
require enabling Flask-Security's global ``SECURITY_REFRESH_TOKEN`` flag, which also
changes browser authentication. Apply the database migration before running the upgraded server.

Malformed requests return HTTP status 400 with validation errors. An invalid, expired,
revoked, or reused refresh token returns HTTP status 401 with ``error`` set to
``"invalid_refresh_token"`` and an ``errors`` list. On that response, authenticate again;
do not retry the rejected token. Ordinary API authorization still depends on the user's
permissions, and refreshing a token does not grant additional permissions.

Use HTTPS, keep passwords and tokens out of logs, and store them in a protected credential
store. Token responses include ``Cache-Control: no-store``. The following examples use
placeholders; do not put real credentials in shell history.

Example requests with curl (``--fail-with-body`` reports HTTP failures):

.. code-block:: bash

    curl --fail-with-body https://company.flexmeasures.io/api/requestAuthToken \
      -H 'Content-Type: application/json' \
      -d '{"email":"user@example.com","password":"<password>","include-refresh-token":true}'

    curl --fail-with-body https://company.flexmeasures.io/api/v3_0/users/1 \
      -H 'Authorization: <access token>'

    curl --fail-with-body https://company.flexmeasures.io/api/refreshAuthToken \
      -H 'Content-Type: application/json' \
      -d '{"refresh-token":"<current refresh token>"}'

    curl --fail-with-body https://company.flexmeasures.io/api/revokeRefreshToken \
      -H 'Content-Type: application/json' \
      -d '{"refresh-token":"<replacement refresh token>"}'

The equivalent Python sequence logs in, accesses the API, refreshes, accesses the API
with the replacement token, and revokes the refresh-token family. This single-process
example keeps tokens in memory; a persistent client should save replacements atomically.
It deliberately does not automatically retry failed refresh requests.

.. code-block:: python

    import getpass
    import requests

    base_url = "https://company.flexmeasures.io"

    def post_token(endpoint, body):
        response = requests.post(
            f"{base_url}/api/{endpoint}", json=body, timeout=30
        )
        if response.status_code == 401:
            raise RuntimeError("Authentication failed; sign in again.")
        response.raise_for_status()
        return response.json()

    tokens = post_token("requestAuthToken", {
        "email": input("Email: "),
        "password": getpass.getpass(),
        "include-refresh-token": True,
    })

    def get_user(tokens):
        response = requests.get(
            f"{base_url}/api/v3_0/users/{tokens['user_id']}",
            headers={"Authorization": tokens["auth_token"]},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    user = get_user(tokens)
    tokens = post_token("refreshAuthToken", {
        "refresh-token": tokens["refresh-token"],
    })
    user = get_user(tokens)
    post_token("revokeRefreshToken", {
        "refresh-token": tokens["refresh-token"],
    })

.. _api_see_other:

See Other (303)
---------------

Some API responses return ``HTTP status 303 (See Other)`` to redirect the client to a different resource.
This can happen when a custom scheduler defines a fallback scheduler, the original scheduling job fails, and the fallback schedule has been computed instead.
In that case, the response includes a ``Location`` header pointing to the fallback schedule endpoint, so clients can automatically retrieve the fallback result.

The response body will contain a JSON message with a ``status`` field set to ``"UNKNOWN_SCHEDULE"`` and a ``message`` field explaining the reason for the redirect.

.. note::

    FlexMeasures' built-in storage scheduler no longer computes a fallback schedule for infeasible problems.
    Instead, ``soc-minima``, ``soc-maxima`` and ``soc-targets`` are relaxed by default (setting ``relax-soc-constraints`` or ``relax-constraints`` to ``false`` keeps them hard, with an explicitly set ``relax-soc-constraints`` taking precedence).
    The hard constraints that remain even after constraint relaxation are ``soc-min``, ``soc-max`` and ``power-capacity`` in the ``flex-model``, and ``site-power-capacity`` in the ``flex-context``.
    The device ``consumption-capacity`` and ``production-capacity`` are not covered by ``relax-constraints`` at all; they stay hard unless you relax them by name, either by setting ``relax-capacity-constraints`` or by setting ``consumption-breach-price`` or ``production-breach-price`` yourself.
    If hard constraints cannot be satisfied, the scheduling job fails and clients receive the failure reason when requesting the schedule.

    For custom schedulers that still define a fallback scheduler, server administrators can configure whether clients receive a 303 redirect (``FLEXMEASURES_FALLBACK_REDIRECT = True``) or whether FlexMeasures follows the fallback automatically and returns the fallback schedule directly (``FLEXMEASURES_FALLBACK_REDIRECT = False``, the default).

Here is a client-side code example in Python for handling 303 redirects (this merely follows the redirect and should be revised to make use of the client's monitoring tools):

.. code-block:: python

    import requests

    def get_schedule(url, params):
        """Request a schedule, following any 303 redirect to a fallback schedule.

        Reference
        ---------
        https://flexmeasures.readthedocs.io/en/latest/api/introduction.html#see-other-303
        """
        response = requests.get(url, params=params)
        if response.status_code == 303:
            fallback_url = response.headers["Location"]
            print(
                f"Schedule at {url} was redirected to a fallback schedule."
                f" Reason: {response.json().get('message')}"
                f" Fetching fallback schedule from {fallback_url} ..."
            )
            response = requests.get(fallback_url, params=params)
            if not response.ok:
                print(f"Failed to fetch fallback schedule: {response.status_code} {response.text}")
        return response

.. _api_background_jobs:

Background job monitoring
--------------------------

Several API endpoints queue background jobs for asynchronous processing (scheduling, forecasting, data ingestion) and return a ``202 Accepted`` response.
These responses include a ``job`` field (the canonical identifier) that clients can use to monitor job progress and retrieve results.
They also include both ``job-url`` for generic status monitoring and (if applicable) ``results-url`` for the sensor-specific results endpoint.

**Example 202 Accepted response from a scheduling endpoint:**

.. code-block:: json

    {
        "status": "ACCEPTED",
        "job": "364bfd06-c1fa-430b-8d25-8f5a547651fb",
        "job-url": "/api/v3_0/jobs/364bfd06-c1fa-430b-8d25-8f5a547651fb",
        "results-url": "/api/v3_0/sensors/3/schedules/364bfd06-c1fa-430b-8d25-8f5a547651fb",
        "message": "Request has been accepted for processing."
    }

**Monitoring job status:**

Clients should use the ``job.id`` to query the unified job status endpoint:

.. code-block:: bash

    GET /api/v3_0/jobs/<job-id>

This returns the current execution status and a human-readable result message. For example:

.. code-block:: python

    import requests
    import time

    def wait_for_job(job_id, job_url, timeout=300, poll_interval=5):
        """Wait for a background job to complete and return the result.

        Parameters
        ----------
        job_id : str
            The UUID of the background job, we use it for logging here..
        job_url : str
            The URL to query for job status (e.g., "/api/v3_0/jobs/<uuid>").
        timeout : int
            Maximum seconds to wait for job completion.
        poll_interval : int
            Seconds between status checks.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = requests.get(job_url)
            if response.status_code not in (200, 202, 422):
                raise RuntimeError(
                    f"Failed to query job status: {response.status_code} {response.text}"
                )

            job_data = response.json()
            status = job_data.get("status")

            if response.status_code == 202:
                print(f"Job {job_id} is still {status.lower()}...")
                time.sleep(poll_interval)
            elif status == "FINISHED":
                return job_data.get("result")
            else:  # Failed, error, etc.
                raise RuntimeError(f"Job failed with status {status}: {job_data.get('message')}")

        raise TimeoutError(f"Job {job_id} did not complete within {timeout} seconds")

.. note::

    For **schedules**, after the job completes successfully, use the job ID (same value as the legacy ``schedule`` field) to retrieve the actual schedule or follow the returned ``results-url``:
    
    .. code-block:: bash
    
        GET /api/v3_0/sensors/<sensor_id>/schedules/<job-id>
    
    For **forecasts**, after the job completes successfully, use the job ID to retrieve the forecast or follow the returned ``results-url``:
    
    .. code-block:: bash
    
        GET /api/v3_0/sensors/<sensor_id>/forecasts/<job-id>

    Both of these endpoints will also return `202 Accepted` if the job is still being computed, so clients can continue to poll them directly if they prefer.

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

.. _api_response_field_naming:

Response field naming (``job``, ``schedule``, ``forecast``)
"""""""""""""""""""""""""""""""""""""""""""""""""""""""""""

Background-job trigger endpoints (e.g. ``POST /sensors/<id>/schedules/trigger``, ``POST /assets/<id>/schedules/trigger``, ``POST /sensors/<id>/forecasts/trigger``) and ``GET /api/v3_0/jobs/<uuid>`` return a canonical ``job`` field (and, for job status, kebab-case metadata fields such as ``func-name``) alongside older field names (``schedule``, ``forecast``, ``func_name``, etc.) kept purely for backward compatibility.
Within API version ``v3.0``, these older field names are additive aliases and will keep working unchanged.

New clients should prefer the canonical fields. Any eventual removal of the older field names is planned to happen only as part of a new, whole API version, following the same versioned deprecation/sunset flow described in :ref:`api_deprecation_hosts`. See the `API v4 planning discussion <https://github.com/FlexMeasures/flexmeasures/discussions/2349>`_ for the current state of that plan.

.. _api_deprecation_hosts:

Hosts
^^^^^

FlexMeasures versions go through the following stages for deprecating major features (such as API versions):

- :ref:`api_deprecation_stage_1`: status 200 (OK) with :ref:`relevant headers<api_deprecation_clients>`, plus a toggle to 410 (Gone) for blackout tests
- :ref:`api_deprecation_stage_2`: status 410 (Gone), plus a toggle to 200 (OK) for sunset rollbacks
- :ref:`api_deprecation_stage_3`: status 410 (Gone)

Let's go over these stages in more detail.
Hosts can customize the dates and information links used in deprecation and sunset headers with ``FLEXMEASURES_DEPRECATION_AND_SUNSET`` (see :ref:`Sunset Configuration<sunset-config>`).

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
