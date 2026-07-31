.. _multi-tenancy:

Multi-tenancy
=============

FlexMeasures is designed as a multi-tenant platform. This means that one FlexMeasures instance can serve multiple tenants, while each tenant keeps its own users, assets, sensors, time series data, forecasts and schedules.

Tenants are represented by accounts. Users belong to exactly one account, and FlexMeasures applies authorization checks throughout the UI and API so that regular tenant users cannot see or change another tenant's data.

Consultancy and B2B2B
--------------------

Consultancy extends this model to multi-level multi-tenancy, sometimes called B2B2B. A consultancy account can have client accounts. Users in the consultancy account with the ``consultant`` user role can access consultancy-related data in those client accounts and can create new client accounts themselves.

This is useful when the host serves several first-level tenants, and some of those tenants manage their own customers on the same FlexMeasures platform.

Recommended tenant structure
----------------------------

We recommend keeping the host account at the top. This account should contain the host's admin users. First-level tenants are client accounts of the host account. If a first-level tenant manages customers itself, make that tenant a consultancy account and add its customers as second-level client accounts.

.. mermaid::

    flowchart TD
        Host["Host account<br>Admin users"]
        TenantA["Tenant A<br>Consultancy account"]
        TenantB["Tenant B"]
        TenantC["Tenant C<br>Consultancy account"]
        ClientA1["Tenant A client 1"]
        ClientA2["Tenant A client 2"]
        ClientC1["Tenant C client 1"]

        Host --> TenantA
        Host --> TenantB
        Host --> TenantC
        TenantA --> ClientA1
        TenantA --> ClientA2
        TenantC --> ClientC1

.. note::

   FlexMeasures does not technically limit the consultancy tree to two levels. A second-level tenant can also add its own clients if that account has the ``Consultancy`` account role and its user has the ``consultant`` role. Hosts can prevent deeper structures by not giving those accounts the ``Consultancy`` account role. Only admin users can grant or remove account roles.

How to manage consultancy tenants
---------------------------------

Make an account a consultancy account
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

An admin user can open the account page in the UI, click *Edit*, and add the ``Consultancy`` account role under *Account roles*.

When creating an account from the CLI, the role can be assigned immediately:

.. code-block:: bash

   $ flexmeasures add account --name "Host" --roles Consultancy

Existing accounts can also be updated through the account API by an admin user, using the ``account_roles`` field on ``PATCH /api/v3_0/accounts/{id}``.

Give a user the consultant role
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

An admin user can open the user's page in the UI, click *Edit*, and add the ``consultant`` user role.

When creating a user from the CLI, the role can be assigned immediately:

.. code-block:: bash

   $ flexmeasures add user --username <username> --email <email-address> --account <account-id> --roles consultant

Add a new client account
^^^^^^^^^^^^^^^^^^^^^^^^

Admin users can create accounts and choose their consultancy account. Consultant users in a ``Consultancy`` account can create client accounts from their own account page with *Add client account*. In that case, FlexMeasures automatically links the new account as a client account of the consultant's own account.

The same behavior is available through ``POST /api/v3_0/accounts``. For consultant users, the created account is automatically linked to their own account as consultancy account.

First account on a new instance
-------------------------------

On a new FlexMeasures instance, the first account still needs to be created with the CLI. We recommend making this first account the host account and assigning the ``Consultancy`` account role to it, so the host can manage first-level client tenants from the start.

After the database is initialized, create the host account and first admin user:

.. code-block:: bash

   $ flexmeasures add account --name "Host" --roles Consultancy
   $ flexmeasures add user --username <admin-username> --email <admin-email-address> --account <host-account-id> --roles admin

The account command prints the new account ID. Use that ID as ``<host-account-id>`` when creating the admin user.
