.. _connection-secrets-dev:

Connection secrets and token schemes
====================================

This page gives plugin and service developers a generic pattern for storing
connection secrets and implementing token lifecycles. It intentionally avoids
provider-specific details, because each integration has its own authorization
contract, expiry semantics and rotation rules.

Use this guidance when an integration needs to keep credentials, API keys,
authorization tokens or other connection material on behalf of an organisation
or asset.


Encrypted JSON secrets
----------------------

Store connection secrets as encrypted JSON documents attached to the account or
asset that owns the connection.

Use account-level secrets for connection material that applies to the whole
organisation, such as credentials for a tenant-wide integration. Use asset-level
secrets for connection material that belongs to a single device, site or
connection endpoint.

The encrypted payload should contain only data needed to establish or refresh a
connection. Keep non-secret metadata, such as a human-readable connection name,
provider strategy identifier, external resource identifier or status flag, in
normal model fields or unencrypted attributes where possible. This keeps list
views and diagnostics useful without exposing credentials.

Recommended JSON shape:

.. code-block:: json

    {
      "example_strategy": {
        "client_id": {
          "ciphertext": "...",
          "key_id": "default",
          "created_at": "2026-06-11T12:00:00+00:00",
          "updated_at": "2026-06-11T12:00:00+00:00"
        },
        "refresh_token": {
          "ciphertext": "...",
          "key_id": "default",
          "expires_at": "2026-06-25T12:00:00+00:00"
        },
        "access_token": {
          "ciphertext": "...",
          "key_id": "default",
          "expires_at": "2026-06-11T12:05:00+00:00",
          "token_type": "Bearer"
        },
        "metadata": {
          "strategy": "example-token-strategy",
          "external_resource_id": "resource-123"
        }
      }
    }

The exact fields can differ per integration, but the storage format should stay
JSON-serializable, versionable and explicit about timestamps. Store timestamps
with timezone information.


Write-only API and UI handling
------------------------------

Treat secret fields as write-only.

API endpoints and UI forms may accept new secrets, but they should not return
the decrypted values. Read responses should expose only safe metadata, for
example whether a secret is configured, when a token expires, when the
connection was last refreshed, or which strategy is active.

When updating secrets, prefer partial updates with clear semantics:

* Omitting a secret field leaves the existing encrypted value unchanged
* Setting a supported secret field replaces that value
* Clearing a secret requires an explicit clear action or explicit ``null`` value

This avoids accidental credential deletion when users edit unrelated connection
metadata.


Initiate token refresh cycles on startup
-----------------------------------------

Most providers will require true credentials only in the first interaction:
username & password to get the access & refresh token, for example.
From then, on the refresh token helps to get by, as long as it does not expire.

A CLI command can be written for this login and seeding of the token refresh cycle.
If no current token is in the database, let your plugin code fail explicitly by
requiring the user to call this CLI command.


Provider strategies
-------------------

Implement provider behavior behind a strategy interface. The core application
should not need to know whether a connection uses a static key, a short-lived
access token, a refresh token, client credentials or another token lifecycle.

A strategy should own at least these responsibilities:

* Validate the encrypted JSON shape it expects
* Decide whether the current access token can be reused
* Refresh or reissue tokens when needed
* Persist rotated tokens back to the encrypted JSON payload
* Report safe metadata for API responses, UI pages and logs

Design strategies so they can handle lifecycle variants without changing API
contracts. Common variants include:

* Static credentials with no token refresh
* Short-lived access tokens derived from long-lived credentials
* Refresh tokens that rotate on every refresh
* Refresh tokens that expire after an absolute lifetime
* One-time authorization codes that are exchanged for durable connection
  material

Do not log decrypted secrets or raw tokens. Log strategy names, connection IDs,
expiry timestamps and error classes instead.


Access-token caching across workers
-----------------------------------

Workers, API processes and scheduled jobs may all need the same connection.
Avoid refreshing access tokens independently in every process.

Persist encrypted access tokens with an ``expires_at`` value in ``secrets`` if
they need to be reused across workers. The database then becomes the shared
coordination point. Use a refresh margin that expires before the token itself,
leaving enough room for clock differences and request retries.

When the persisted token is missing or near expiry, acquire a short-lived
database lock before refreshing the token. This prevents several workers from
refreshing the same connection at the same time. After a successful refresh,
persist the new encrypted access token and any durable rotated material, such as
refresh tokens, to the encrypted JSON payload.

Redis or another shared cache can still be used as an optimization, but the
encrypted database payload should remain the durable source of truth for tokens
and rotation metadata.


Refresh-token rotation
----------------------

Some token schemes return a new refresh token whenever an access token is
refreshed. Treat this as an atomic rotation:

* Use the previous refresh token only for the refresh request
* Persist the new refresh token immediately after a successful response
* Replace any cached access token after the durable secret update succeeds
* Keep enough error context to tell users that reconnecting may be required

If the process crashes between receiving and persisting a rotated refresh token,
the connection may no longer be recoverable automatically. Strategies should
surface this state clearly and avoid repeated refresh attempts that will keep
failing.


Key configuration
-----------------

Encryption keys must come from host configuration, not from source control.
They should be strong, environment-specific and available to every API process,
worker and scheduled job that needs to decrypt connection secrets.
Production deployments must set ``FLEXMEASURES_SECRETS_ENCRYPTION_KEY``; only
non-production environments may fall back to ``SECRET_KEY``.

Hosts should plan for key rotation before production use. A practical approach
is to support a primary key for new writes and one or more previous keys for
reading existing payloads during a migration window. After all payloads have
been re-encrypted with the primary key, old keys can be removed.

Changing the key without a migration plan can make existing connection secrets
undecryptable. Document the operational steps for each deployment and test them
against a staging database before rotating production keys.
