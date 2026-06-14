.. _storing_connection_secrets:

Storing connection secrets
==========================

Plugins which connect FlexMeasures accounts or assets to external platforms often
need to store credentials, refresh tokens, access tokens or connection-specific
passwords. Store such values in the ``secrets`` JSON field of the relevant
account or asset, rather than in ``attributes`` or plugin configuration files.

The ``secrets`` field is intended to be write-only from API and UI flows: users
can provide or replace secret values, but normal responses should return only
redacted metadata such as whether a value is set and when it expires. Trusted
server-side plugin code can decrypt and use the value when it performs work for
the account or asset.

Use ``flexmeasures.utils.secrets_utils`` for secret handling:

.. code-block:: python

    from flexmeasures.utils.secrets_utils import (
        SecretsEncryptor,
        get_secret,
        redact_secrets,
        set_secret,
    )

    encryptor = SecretsEncryptor.from_current_app()

    my_account.secrets = set_secret(
        my_account.secrets,
        "3rdparty-platform.refresh_token",
        refresh_token,
        encryptor=encryptor,
        metadata={"expires_at": refresh_token_expires_at.isoformat()},
    )

    refresh_token = get_secret(
        my_account.secrets,
        "3rdparty-platform.refresh_token",
        encryptor=encryptor,
    )

    response_payload = redact_secrets(my_account.secrets)

The encrypted values are protected by
``FLEXMEASURES_SECRETS_ENCRYPTION_KEY``. This setting accepts an arbitrary
non-empty string, which FlexMeasures derives into a Fernet-compatible key. In
development and tests, FlexMeasures can fall back to ``SECRET_KEY``. Production
installations must set a dedicated encryption key so session signing can be
rotated independently from stored connection credentials.

More details and best practices for storing connection secrets are in the :ref:`connection_secrets_dev` section.


Initiate token refresh cycles on startup
-----------------------------------------

Most providers will require true credentials only in the first interaction:
username & password to get the access & refresh token, for example.
From then, on the refresh token helps to get by, as long as it does not expire.

A CLI command can be written for this login and seeding of the token refresh cycle.
If no current token is in the database, let your plugin code fail explicitly by
requiring the user to call this CLI command.


Token lifecycle strategies
---------------------------

External platforms do not all follow the same token refresh semantics. Keep the
provider-specific HTTP calls in your plugin, and use FlexMeasures utilities only
for encryption, redaction and updating stored token state.

The following token lifecycle patterns are supported by
``TokenRefreshResult`` and ``apply_token_refresh_result``:

* A refresh operation returns a new access token: set
  ``TokenRefreshResult.access_token`` and ``access_token_expires_at``.
* A refresh operation rotates the refresh token: set
  ``TokenRefreshResult.refresh_token`` and ``refresh_token_expires_at``.
* A refresh operation extends an existing access token without returning a new token:
  leave ``access_token`` as ``None`` and set ``access_token_expires_at``.
* Access tokens are minted separately from refresh-token rotation: call
  ``apply_token_refresh_result`` once for the refreshed long-lived credential
  and again when a short-lived access token is minted.

A provider strategy can translate its HTTP response into a
``TokenRefreshResult`` and let FlexMeasures update the encrypted JSON state:

.. code-block:: python

    from flexmeasures.utils.secrets_utils import (
        SecretsEncryptor,
        TokenRefreshResult,
        apply_token_refresh_result,
        get_secret,
    )

    encryptor = SecretsEncryptor.from_current_app()

    refresh_token = get_secret(
        my_account.secrets,
        "3rdparty-platform.refresh_token",
        encryptor=encryptor,
    )

    token_response = refresh_with_external_platform(refresh_token)

    my_account.secrets = apply_token_refresh_result(
        my_account.secrets,
        "3rdparty-platform",
        TokenRefreshResult(
            access_token=token_response.get("access_token"),
            refresh_token=token_response.get("refresh_token"),
            access_token_expires_at=token_response.get("access_token_expires_at"),
            refresh_token_expires_at=token_response.get("refresh_token_expires_at"),
            token_type=token_response.get("token_type"),
            metadata={"scope": token_response.get("scope")},
        ),
        encryptor=encryptor,
    )

If a platform only extends the lifetime of the existing access token, keep
``access_token`` set to ``None`` and provide the new
``access_token_expires_at``. The existing encrypted token is kept, and only its
metadata is updated.

For multi-worker deployments, plugins should cache short-lived access tokens in
``secrets`` with an ``expires_at`` value and refresh them before they expire. A
provider-specific helper can use a database lock around refresh work so only one
worker refreshes a token while other workers reuse the updated token state.

