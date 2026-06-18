.. _connection_secrets_dev:

Connection secrets
==================

If you make a secure connection to an external platform, FlexMeasures can store credentials,
API keys and tokens in the ``secrets`` JSON field of the account or asset that owns the connection.
Each secret value is encrypted separately and stored together with metadata such as its encryption
key ID and timestamps. Developers normally do not need to read or modify this
JSON structure directly.

For implementation examples, token lifecycle strategies and manually seeding a
credential through the CLI, see :ref:`storing_connection_secrets`. The complete
utility API is available in :mod:`flexmeasures.utils.secrets_utils`.


Recommended practices
---------------------

Encryption key configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Configure :ref:`flexmeasures_secrets_encryption_keys` with strong,
environment-specific key material and make the same keyring available to every
API process, worker and scheduled job. FlexMeasures refuses to create or
decrypt connection secrets without this setting. Keep previous keys available
while encrypted values still refer to them.


Write-only API and UI
^^^^^^^^^^^^^^^^^^^^^

Treat secrets as write-only in API and UI flows. Accept new or replacement
values, but never return plaintext secrets. Responses should contain only
redacted information such as whether a value is set and when it expires.

For administrator-level maintenance, use ``flexmeasures edit secret`` to store
or replace one account or asset secret and ``flexmeasures delete secret`` to
remove one. Prefer the edit command's ``--prompt`` option so secret values do
not enter shell history.


Use the secret utilities
^^^^^^^^^^^^^^^^^^^^^^^^

Use :func:`flexmeasures.utils.secrets_utils.set_secret` for individual
credentials. For token refresh flows, prefer
:class:`flexmeasures.utils.secrets_utils.TokenRefreshResult` together with
:func:`flexmeasures.utils.secrets_utils.apply_token_refresh_result`. They safely
handle replacement tokens, rotated refresh tokens and providers that only
extend the expiry of an existing token.

Use :func:`flexmeasures.utils.secrets_utils.get_secret_overview` to build safe
secret listings with their paths and optional expiration times, without
exposing encrypted values or unrelated metadata.


Refresh early in multi-worker deployments
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Store reusable access tokens and their expiry metadata in ``secrets`` so all
workers share the same token state. Refresh with time to spare before expiry to
allow for clock differences, retries and concurrent workers. In high-traffic
integrations, use database locking so only one worker performs a refresh. See
the refresh-leeway example in :ref:`initiating_connection_tokens`.
