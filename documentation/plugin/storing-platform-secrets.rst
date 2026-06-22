.. _storing_connection_secrets:

Storing connection secrets
==========================

Plugins that connect FlexMeasures accounts or assets to external platforms often
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
``FLEXMEASURES_SECRETS_ENCRYPTION_KEYS``. This setting accepts arbitrary
non-empty strings, which FlexMeasures derives into Fernet-compatible keys.
Hosts must configure this keyring before secrets can be stored
- FlexMeasures will print a warning if it is not set and hints how to initialize it.

More details and best practices for storing connection secrets are in the :ref:`connection_secrets_dev` section.


Token lifecycle strategies
-----------------------------

External platforms do not all require the same interactions to maintain a connection.
Initial login, token refresh and token expiry can all work rather differently.
You could say that they implement different "token lifecycle strategies".

That's why our advice is to keep the provider-specific HTTP calls in your plugin,
and use FlexMeasures utilities only for encryption, redaction and updating stored token state.

The following token lifecycle strategies are supported by
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

Your task is to translate the HTTP response from the platform provider into a
``TokenRefreshResult`` and let FlexMeasures update the encrypted JSON state.
Let's look at an example:

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

    # this function would be written by you
    token_response = refresh_with_external_platform(refresh_token)

    # here you translate the response - consult the platform docs
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

This varies by platform - for instance, if a platform only extends the lifetime
of the existing access token (instead of returning a new one), keep
``access_token`` set to ``None`` and provide the new ``access_token_expires_at``.
The existing encrypted token is kept, and only its metadata is updated.

Your plugin should also decide when to request a refreshed access token, e.g.:

.. code-block:: python

    3RDPARTY_PLATFORM_TOKEN_LEEWAY = timedelta(seconds=120)
    # you might get this info with `secret_utils.get_secret()`
    if current_access_token_expires_at > now + 3RDPARTY_PLATFORM_TOKEN_LEEWAY:
        return access_token
    response = send_request_to_3rdparty_platform()
    access_token = response.text
    refresh_account.secrets = apply_token_refresh_result(...)



.. _initiating_connection_tokens:

Initiating tokens (before app startup)
-----------------------------------------

Most providers will require the true credentials only in the first interaction:
For example: username & password to get the access & refresh token.
From then on, the refresh token helps to get by (as long as it does not expire).

In your plugin, you can write a CLI command to perform this login, get your first
refresh token and save it as a secret (see `set_secret()` and `apply_token_refresh_result()`
in utils/secrets_utils.py).
The token lifecycle strategy (see above) will depend on the platform you connect to.

Also advisable: if no current token is in the database, let your plugin code fail
explicitly and advise the user to call your login CLI command.


Alternatively, you can manually store a known credential: Use ``flexmeasures edit secret`` with
an account or asset ID, a dot-separated secret path and either ``--value`` or
``--prompt`` (to paste the secret insted of typing it).
Use ``--metadata`` for non-secret JSON metadata such as expiry
timestamps.
