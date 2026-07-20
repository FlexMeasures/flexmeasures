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

All API responses include a ``FlexMeasures-Version`` header with the current server version, and responses from versioned API endpoints (e.g. under ``/api/v3_0``) also include an ``API-Version`` header indicating the API version:

.. code-block:: http

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

.. note:: Each access token has a limited lifetime, see :ref:`api_auth`.

.. _api_see_other:

See Other (303)
---------------

Some API responses return ``HTTP status 303 (See Other)`` to redirect the client to a different resource.
This happens, for example, when a scheduling job fails and a fallback schedule has been computed instead.
In that case, the response includes a ``Location`` header pointing to the fallback schedule endpoint, so clients can automatically retrieve the fallback result.

The response body will contain a JSON message with a ``status`` field set to ``"UNKNOWN_SCHEDULE"`` and a ``message`` field explaining the reason for the redirect.

.. note::

    The fallback schedule mechanism activates when the main scheduler encounters an infeasible problem (i.e. when constraints cannot be satisfied).
    This is less likely to happen when ``"relax-constraints": true`` is set in the ``flex-context``, as constraint relaxation softens most infeasibility-causing constraints.
    The hard constraints that remain even after constraint relaxation are ``soc-min``, ``soc-max``, ``soc-targets`` and ``power-capacity`` in the ``flex-model``, and ``site-power-capacity`` in the ``flex-context``.

    Server administrators can configure whether clients receive a 303 redirect (``FLEXMEASURES_FALLBACK_REDIRECT = True``) or whether FlexMeasures follows the fallback automatically and returns the fallback schedule directly (``FLEXMEASURES_FALLBACK_REDIRECT = False``, the default).

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

Deprecated response fields
^^^^^^^^^^^^^^^^^^^^^^^^^^^

In addition to deprecating entire endpoints, we sometimes deprecate individual fields in API responses while maintaining backward compatibility by including both the legacy and canonical fields.
When this happens, responses include a ``Deprecation`` response header with the deprecation date, a ``Link`` header pointing to migration guidance, and a ``FlexMeasures-Deprecated-Response-Fields`` header identifying the deprecated fields in that response.

For example, when scheduling endpoints switched from ``schedule`` to ``job`` as the canonical field identifier for background jobs, a response that still contains the legacy ``schedule`` field also carries deprecation headers:

.. code-block:: http

    HTTP/1.1 202 Accepted
    Deprecation: Wed, 01 Jul 2026 00:00:00 GMT
    Link: <https://flexmeasures.readthedocs.io/latest/api/v3_0.html#post--api-v3_0-sensors-id-schedules-trigger>; rel="deprecation"; type="text/html"
    FlexMeasures-Deprecated-Response-Fields: schedule
    Content-Type: application/json

    {
        "status": "ACCEPTED",
        "job": "364bfd06-c1fa-430b-8d25-8f5a547651fb",
        "schedule": "364bfd06-c1fa-430b-8d25-8f5a547651fb",
        "job-url": "/api/v3_0/jobs/364bfd06-c1fa-430b-8d25-8f5a547651fb",
        "results-url": "/api/v3_0/sensors/3/schedules/364bfd06-c1fa-430b-8d25-8f5a547651fb"
    }

In this example, clients should treat ``job`` as the canonical field and ``schedule`` as a backward-compatible alias.
The ``FlexMeasures-Deprecated-Response-Fields`` header tells clients which response fields are deprecated, the ``Deprecation`` header tells clients when they were deprecated, and the ``Link`` header points to migration guidance for this endpoint.

Professional API users should monitor API responses for the ``"Deprecation"`` and ``"Sunset"`` response headers [see `draft-ietf-httpapi-deprecation-header-02 <https://datatracker.ietf.org/doc/draft-ietf-httpapi-deprecation-header/>`_ and `RFC 8594 <https://www.rfc-editor.org/rfc/rfc8594>`_, respectively], so system administrators can be warned when using API endpoints that are flagged for deprecation and/or are likely to become unresponsive in the future.
The ``Deprecation`` header may describe either the endpoint itself or specific response fields.
Clients can tell the difference by checking for ``FlexMeasures-Deprecated-Response-Fields``: if it is present, only the named response fields are deprecated; if it is absent, the deprecation applies to the endpoint or API version as a whole.

For deprecated response fields, clients should:

- Monitor the ``Deprecation`` response header to detect deprecated API behavior.
- Use the ``FlexMeasures-Deprecated-Response-Fields`` header to identify which response fields are deprecated.
- Follow the ``Link`` response header to find migration guidance.
- Migrate to use the canonical field names documented in the API schema.
- Plan upgrades based on the deprecation guidance to avoid breakage when deprecated fields are eventually removed in a future API version.

Client code should therefore inspect both headers and body fields, for example:

.. code-block:: python

    response = requests.post(trigger_url, json=payload, headers=headers)
    response.raise_for_status()

    deprecated_fields = response.headers.get("FlexMeasures-Deprecated-Response-Fields")
    if deprecated_fields:
        print(f"Deprecated response fields detected: {deprecated_fields}")
        print(f"See {response.headers.get('Link')}")

    data = response.json()
    job_id = data["job"]

For endpoint deprecations, the deprecation header field shows an `IMF-fixdate <https://www.rfc-editor.org/rfc/rfc7231#section-7.1.1.1>`_ indicating when the API endpoint was deprecated.
For deprecated response fields, the deprecation header field also shows an IMF-fixdate, while the presence of the ``FlexMeasures-Deprecated-Response-Fields`` header narrows the deprecation to the named response fields.
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
