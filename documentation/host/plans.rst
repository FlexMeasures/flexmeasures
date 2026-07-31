.. _plans-and-rate-limiting:

Plans and rate-limiting
=======================

FlexMeasures rate-limits its API, to protect the server against clients which ask for more than their fair share ―
in particular against clients which re-trigger expensive computations like scheduling in a tight loop.

Two limits apply. A default limit applies to every API endpoint, and a stricter limit applies to the endpoints
which trigger scheduling and forecasting. Requests which exceed a limit are answered with a ``429`` status code,
and a ``Retry-After`` header telling the client how long to wait.

Counts are kept in Redis (see :ref:`redis-config`), so that all your workers share them. If Redis cannot be
reached, FlexMeasures lets requests through rather than refusing them.

Both limits are configured server-wide, and can be overridden per account by putting the account on a plan.
The settings themselves are documented under :ref:`rate-limiting-config`.


How the two limits count
-------------------------

- The **default limit** counts *every* request, including the ones we refuse. The limiter runs before
  authentication, so requests without valid credentials are counted, too (per IP address, as there is no user
  to count them against). This is what bounds a client who keeps sending requests we refuse.
- The **trigger limit** only counts triggers we *accepted*. It exists to protect the expensive computation which
  a trigger sets in motion, and a request we rejected ― because its payload did not validate, or because the
  asset belongs to someone else ― cost us no computation. In other words, a client who made a mistake in their
  flex-model does not pay for it out of their scheduling budget (they still pay for it out of the default one).

.. _rate-limiting-plans:

Managing plans
---------------

Individual accounts can be given their own limits, which take precedence over the server-wide settings, by putting
the account on a plan. A plan (``flexmeasures.data.models.user.Plan``) bundles the rate limits and quotas which
apply to the accounts assigned to it, so that it can be shared as a tier (say, "Free" and "Pro").

Create a plan with ``flexmeasures add plan``:

.. code-block:: bash

    $ flexmeasures add plan --name Pro --trigger-rate-limit "60 per 5 minutes" --rate-limit-key account

List the plans you created, with the limits each of them sets, using ``flexmeasures show plans``:

.. code-block:: bash

    $ flexmeasures show plans

A plan's ``default_rate_limit``, ``trigger_rate_limit`` and ``rate_limit_key`` override the server-wide settings
for the accounts on that plan. A field left unset (``None``) falls back to the server-wide setting, so an account
on a plan which only sets ``trigger_rate_limit`` is treated like everybody else for all other requests. Use the
value ``"unlimited"`` to exempt an account from a limit altogether.

Edit a plan with ``flexmeasures edit plan``, which identifies the plan by its ID (so that ``--name`` can rename it),
and changes only the fields you pass:

.. code-block:: bash

    $ flexmeasures edit plan --id 2 --trigger-rate-limit "120 per 5 minutes"

To have accounts on a plan fall back on the server-wide setting again, clear the field rather than setting it:

.. code-block:: bash

    $ flexmeasures edit plan --id 2 --clear trigger-rate-limit

Retiring a plan
^^^^^^^^^^^^^^^^

A plan usually reflects a contractual agreement, so rather than editing a plan on which there are already accounts,
retire it and create the plan you want to offer instead:

.. code-block:: bash

    $ flexmeasures edit plan --id 2 --legacy

A legacy plan keeps applying to the accounts already on it, but is no longer offered when assigning a plan.
Bring it back with ``--no-legacy``.

Assigning an account to a plan
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Admins assign an account to a plan from the account page in the UI, or through the API:

.. code-block:: bash

    PATCH /api/v3_0/accounts/<id>       {"plan_id": 2}

Which plan an account is on decides what it may ask of the server, so only platform admins may change it.

Quotas
-------

Plans also carry quotas (``max_users``, ``max_assets`` and ``max_clients``, the latter capping the number of client
accounts a consultancy account may manage). These are not enforced yet, which is why ``flexmeasures show plans``
leaves them out for now.

.. note:: Changing an account's ``rate_limit_key`` orphans the counters it has in Redis (the old keys simply expire),
          so the account may get a fresh budget for the remainder of the current window. Harmless, but worth knowing
          when you wonder why a plan change handed someone a clean slate.
