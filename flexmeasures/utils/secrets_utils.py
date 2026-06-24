from __future__ import annotations

import base64
import json
import os
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypedDict

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from flask import current_app

from flexmeasures.utils.time_utils import as_utc_isoformat, server_now

if TYPE_CHECKING:
    from flexmeasures.data.models.generic_assets import GenericAsset
    from flexmeasures.data.models.user import Account


class SecretsError(Exception):
    """Raised when secret handling fails."""


class InvalidSecretsEncryptionKey(SecretsError):
    """Raised when a usable encryption key cannot be loaded."""


class SecretsDecryptionError(SecretsError):
    """Raised when a value cannot be decrypted."""


_KDF_OUTPUT_BYTES = 32
_KDF_INFO = b"flexmeasures:connection-secrets:v1"
_CIPHERTEXT_FIELD = "ciphertext"
_CONNECTION_SECRETS_KEY_VALUE_GENERATOR = (
    "import secrets; print(secrets.token_urlsafe(32))"
)
_CONNECTION_SECRETS_SETTING_GENERATOR = (
    'import json, secrets; print(json.dumps({"1": secrets.token_urlsafe(32)}))'
)
_TOTP_SECRETS_KEY_VALUE_GENERATOR = (
    "from passlib import totp; print(totp.generate_secret())"
)
_TOTP_SECRETS_SETTING_GENERATOR = 'import json; from passlib import totp; print(json.dumps({"1": totp.generate_secret()}))'


class _SecretOverviewRequired(TypedDict):
    path: str


class SecretOverview(_SecretOverviewRequired, total=False):
    expires_at: datetime


def format_keyring_config_help(
    setting_name: str,
    *,
    purpose: str,
    filename: str | None = None,
    key_value_generator_python: str = _CONNECTION_SECRETS_KEY_VALUE_GENERATOR,
    setting_generator_python: str = _CONNECTION_SECRETS_SETTING_GENERATOR,
) -> str:
    """Return instructions for configuring a dictionary-based secret setting.

    :param setting_name: Name of the FlexMeasures configuration setting.
    :param purpose: Short explanation of what the setting protects.
    :param filename: Optional instance-path file where the setting can be stored.
    :param key_value_generator_python: Python snippet which prints one secret.
    :param setting_generator_python: Python snippet which prints the JSON setting.
    """
    file_instructions = ""
    if filename is not None:
        file_instructions = f"""

        OR you can create a secret key file (this example works only on Unix):

        mkdir -p {os.path.dirname(filename)}
        echo "{{\\"1\\": \\"$(python3 -c '{key_value_generator_python}')\\"}}" > {filename}
        """
    return f"""
        Error: No {setting_name} set ({purpose}).

        Configure {setting_name} as a JSON dictionary from key IDs to secret values.

        You can add the {setting_name} setting to your conf file (this example works only on Unix):

        echo "{setting_name}={{\\"1\\": \\"`python3 -c '{key_value_generator_python}'`\\"}}" >> ~/.flexmeasures.cfg

        OR you can add an env var:

        export {setting_name}='{{"1": "xxxxxxxxxxxxxxx"}}'
        (on windows, use "set" instead of "export")
        {file_instructions}

        You can also use Python to create a good setting value:

        python3 -c '{setting_generator_python}'

        """


def set_totp_secrets(app, filename: str = "totp_secrets") -> None:
    """Set the ``SECURITY_TOTP_SECRETS`` setting or exit app startup.

    :param app: Flask app whose config should receive the setting.
    :param filename: File name in the app instance path to check after config
        and environment values.
    """
    setting_name = "SECURITY_TOTP_SECRETS"
    purpose = "required for two-factor authentication"

    if app.config.get(setting_name, None) is not None:
        return
    configured_value = os.environ.get(setting_name, None)
    if configured_value is not None:
        try:
            app.config[setting_name] = json.loads(configured_value)
            return
        except json.JSONDecodeError:
            app.logger.error(
                f"Error: The environment variable {setting_name} is not valid JSON."
            )
            sys.exit(2)

    path = os.path.join(app.instance_path, filename) if filename else None
    if path is not None:
        try:
            with open(path) as keyring_file:
                configured_value = json.loads(keyring_file.read())
            if isinstance(configured_value, dict):
                app.config[setting_name] = configured_value
                return
            log_keyring_config_error_and_exit(app, setting_name, path)
        except json.JSONDecodeError:
            log_keyring_config_error_and_exit(app, setting_name, path)
        except (IOError, UnicodeDecodeError):
            pass

    app.logger.error(
        format_keyring_config_help(
            setting_name,
            purpose=purpose,
            filename=path,
            key_value_generator_python=_TOTP_SECRETS_KEY_VALUE_GENERATOR,
            setting_generator_python=_TOTP_SECRETS_SETTING_GENERATOR,
        )
    )
    sys.exit(2)


def log_keyring_config_error_and_exit(app, setting_name: str, filename: str) -> None:
    """Log invalid keyring-file instructions and exit app startup.

    :param app: Flask app whose logger should receive the message.
    :param setting_name: Name of the FlexMeasures configuration setting.
    :param filename: File path containing an invalid value.
    """
    app.logger.error(
        """
        ERROR: The file %s exists but does not contain a valid dictionary for %s.

        The correct format is:

        {"1": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}

        """
        % (filename, setting_name)
    )
    sys.exit(2)


def set_secret_key(app, filename: str = "secret_key") -> None:
    """Set the ``SECRET_KEY`` setting or exit app startup.

    :param app: Flask app whose config should receive the setting.
    :param filename: File name in the app instance path to check after config
        and environment values.
    """
    secret_key = app.config.get("SECRET_KEY", None)
    if secret_key is not None:
        return
    secret_key = os.environ.get("SECRET_KEY", None)
    if secret_key is not None:
        app.config["SECRET_KEY"] = secret_key
        return
    filename = os.path.join(app.instance_path, filename)
    try:
        with open(filename, "rb") as secret_key_file:
            app.config["SECRET_KEY"] = secret_key_file.read()
    except IOError:
        app.logger.error(
            """
        Error: No secret key set.

        You can add the SECRET_KEY setting to your conf file (this example works only on Unix):

        echo "SECRET_KEY=\\"`python3 -c 'import secrets; print(secrets.token_hex(24))'`\\"" >> ~/.flexmeasures.cfg

        OR you can add an env var:

        export SECRET_KEY=xxxxxxxxxxxxxxx
        (on windows, use "set" instead of "export")

        OR you can create a secret key file (this example works only on Unix):

        mkdir -p %s
        head -c 24 /dev/urandom > %s

        You can also use Python to create a good secret:

        python3 -c "import secrets; print(secrets.token_urlsafe())"

        """
            % (os.path.dirname(filename), filename)
        )

        sys.exit(2)


def derive_fernet_key(secret: str, *, salt: str = "flexmeasures-secrets") -> bytes:
    """Derive a Fernet-compatible key from an arbitrary non-empty secret.

    :param secret: Master secret from configuration.
    :param salt: Context-specific salt for key derivation.
    :return: URL-safe base64-encoded key accepted by Fernet.
    """
    if not isinstance(secret, str) or not secret.strip():
        raise InvalidSecretsEncryptionKey("Secret encryption key must be non-empty.")

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_KDF_OUTPUT_BYTES,
        salt=salt.encode("utf-8"),
        info=_KDF_INFO,
    )
    derived = hkdf.derive(secret.encode("utf-8"))
    return base64.urlsafe_b64encode(derived)


@dataclass(frozen=True, slots=True)
class SecretsEncryptor:
    """Encrypt and decrypt connection secrets with the configured master key.

    :param encryption_keys: Mapping from key IDs to master key material.
    :param key_id: Identifier of the key used for new encryption. If empty, the
        latest key ID in ``encryption_keys`` is used.
    """

    encryption_keys: dict[str, str]
    key_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.encryption_keys, dict):
            raise InvalidSecretsEncryptionKey(
                "Secret encryption keys must be a non-empty dictionary."
            )
        encryption_keys = _normalize_keyring(self.encryption_keys)
        key_id = self.key_id if self.key_id else _latest_key_id(encryption_keys)
        if not encryption_keys:
            raise InvalidSecretsEncryptionKey(
                "Secret encryption keys must contain at least one non-empty string."
            )
        if not isinstance(key_id, str) or not key_id.strip():
            raise InvalidSecretsEncryptionKey("Secret encryption key ID is required.")
        if key_id not in encryption_keys:
            raise InvalidSecretsEncryptionKey(
                f"Secret encryption key {key_id!r} is not configured."
            )
        object.__setattr__(self, "encryption_keys", encryption_keys)
        object.__setattr__(self, "key_id", key_id)

    @classmethod
    def from_current_app(cls) -> "SecretsEncryptor":
        """Create an encryptor from Flask configuration.

        ``FLEXMEASURES_SECRETS_ENCRYPTION_KEYS`` must be configured before
        connection secrets can be stored or decrypted.
        """
        encryption_keys = current_app.config.get("FLEXMEASURES_SECRETS_ENCRYPTION_KEYS")
        if encryption_keys is None:
            help_msg = format_keyring_config_help(
                "FLEXMEASURES_SECRETS_ENCRYPTION_KEYS",
                purpose="required before storing connection secrets",
                key_value_generator_python=_CONNECTION_SECRETS_KEY_VALUE_GENERATOR,
                setting_generator_python=_CONNECTION_SECRETS_SETTING_GENERATOR,
            )
            raise InvalidSecretsEncryptionKey(help_msg)
        if not isinstance(encryption_keys, dict) or not encryption_keys:
            raise InvalidSecretsEncryptionKey(
                "FLEXMEASURES_SECRETS_ENCRYPTION_KEYS must be a non-empty dictionary."
            )
        return cls(encryption_keys=encryption_keys)

    @property
    def fernet(self) -> Fernet:
        """Fernet instance derived from the current master key."""
        return self._fernet_for(self.key_id)

    def _fernet_for(self, key_id: str) -> Fernet:
        try:
            encryption_key = self.encryption_keys[key_id]
        except KeyError as exc:
            raise InvalidSecretsEncryptionKey(
                f"Secret encryption key {key_id!r} is not configured."
            ) from exc
        return Fernet(derive_fernet_key(encryption_key))

    def encrypt(self, value: str) -> dict[str, Any]:
        """Encrypt a string and return a JSON-serializable envelope.

        :param value: Plaintext secret value to encrypt.
        :return: Dict containing ciphertext, key ID and timestamps.
        """
        if not isinstance(value, str):
            raise SecretsError("Only string secret values can be encrypted.")
        now = as_utc_isoformat(server_now())
        return {
            _CIPHERTEXT_FIELD: self.fernet.encrypt(value.encode("utf-8")).decode(
                "utf-8"
            ),
            "key_id": self.key_id,
            "created_at": now,
            "updated_at": now,
        }

    def decrypt(self, envelope: dict[str, Any] | str) -> str:
        """Decrypt an encrypted envelope or raw Fernet token.

        :param envelope: Dict with a ``ciphertext`` field, or a raw token.
        :return: Decrypted plaintext value.
        """
        token = (
            envelope.get(_CIPHERTEXT_FIELD) if isinstance(envelope, dict) else envelope
        )
        if not isinstance(token, str) or not token:
            raise SecretsDecryptionError("Secret envelope does not contain ciphertext.")
        if isinstance(envelope, dict) and isinstance(envelope.get("key_id"), str):
            key_ids = [envelope["key_id"]]
        else:
            key_ids = [
                self.key_id,
                *[key for key in self.encryption_keys if key != self.key_id],
            ]
        for key_id in key_ids:
            try:
                raw = self._fernet_for(key_id).decrypt(token.encode("utf-8"))
            except InvalidToken:
                continue
            return raw.decode("utf-8")
        raise SecretsDecryptionError("Invalid secret token.")


def _normalize_keyring(encryption_keys: dict[str, str]) -> dict[str, str]:
    """Return a copy of the keyring with non-empty string values only."""
    normalized_keys = {
        str(key_id): key
        for key_id, key in encryption_keys.items()
        if isinstance(key, str) and key.strip()
    }
    if not normalized_keys:
        raise InvalidSecretsEncryptionKey(
            "FLEXMEASURES_SECRETS_ENCRYPTION_KEYS must contain non-empty string values."
        )
    return normalized_keys


def _latest_key_id(encryption_keys: dict[str, str]) -> str:
    """Return the latest key ID from a keyring (dictionary of encryption keys)."""
    numeric_key_ids = [
        int(key_id) for key_id in encryption_keys if str(key_id).isdigit()
    ]
    if numeric_key_ids:
        return str(max(numeric_key_ids))
    return sorted(encryption_keys)[-1]


def _path_parts(path: str | tuple[str, ...] | list[str]) -> list[str]:
    """Return a list of non-empty string parts from a dot-separated path or sequence."""
    if isinstance(path, str):
        parts = [part for part in path.split(".") if part]
    else:
        parts = list(path)
    if not parts or any(not isinstance(part, str) or not part for part in parts):
        raise ValueError("Secret path must contain at least one non-empty string part.")
    return parts


def set_secret(
    secrets: dict[str, Any] | None,
    path: str | tuple[str, ...] | list[str],
    value: str,
    *,
    encryptor: SecretsEncryptor | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a copy of ``secrets`` with an encrypted value set at ``path``.

    :param secrets: Existing secrets dictionary, or ``None`` for a new one.
    :param path: Dot-separated path or sequence of keys where the value is stored.
    :param value: Plaintext secret value to encrypt.
    :param encryptor: Optional encryptor; defaults to app configuration.
    :param metadata: Optional non-secret metadata to store with the envelope.
    """
    encryptor = encryptor or SecretsEncryptor.from_current_app()
    updated = deepcopy(secrets or {})
    current = updated
    parts = _path_parts(path)
    for part in parts[:-1]:
        current = current.setdefault(part, {})
        if not isinstance(current, dict):
            raise ValueError(f"Secret path conflicts with non-object value at {part}.")
    envelope = encryptor.encrypt(value)
    if metadata:
        envelope.update(metadata)
    current[parts[-1]] = envelope
    return updated


def delete_secret(
    secrets: dict[str, Any] | None,
    path: str | tuple[str, ...] | list[str],
) -> dict[str, Any]:
    """Return a copy of ``secrets`` without the value at ``path``.

    Empty dictionaries containing the deleted value are removed as well.

    :param secrets: Existing secrets dictionary.
    :param path: Dot-separated path or sequence of keys to remove.
    :raises KeyError: If the path does not exist.
    """
    updated = deepcopy(secrets or {})
    current: Any = updated
    parents: list[tuple[dict[str, Any], str]] = []
    parts = _path_parts(path)
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise KeyError("Secret path does not exist.")
        parents.append((current, part))
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise KeyError("Secret path does not exist.")
    del current[parts[-1]]

    for parent, part in reversed(parents):
        child = parent[part]
        if isinstance(child, dict) and not child:
            del parent[part]
        else:
            break
    return updated


def store_account_secret(
    account: "Account",
    path: str | tuple[str, ...] | list[str],
    value: str,
    *,
    metadata: dict[str, Any] | None = None,
    encryptor: SecretsEncryptor | None = None,
) -> dict[str, Any]:
    """Store an encrypted secret on an account and return its secrets dict.

    :param account: Account whose ``secrets`` field should be updated.
    :param path: Dot-separated path or sequence of keys where the value is stored.
    :param value: Plaintext secret value to encrypt.
    :param metadata: Optional non-secret metadata to store with the envelope.
    :param encryptor: Optional encryptor; defaults to app configuration.
    """
    account.secrets = set_secret(
        account.secrets,
        path,
        value,
        metadata=metadata,
        encryptor=encryptor,
    )
    return account.secrets


def store_asset_secret(
    asset: "GenericAsset",
    path: str | tuple[str, ...] | list[str],
    value: str,
    *,
    metadata: dict[str, Any] | None = None,
    encryptor: SecretsEncryptor | None = None,
) -> dict[str, Any]:
    """Store an encrypted secret on an asset and return its secrets dict.

    :param asset: Generic asset whose ``secrets`` field should be updated.
    :param path: Dot-separated path or sequence of keys where the value is stored.
    :param value: Plaintext secret value to encrypt.
    :param metadata: Optional non-secret metadata to store with the envelope.
    :param encryptor: Optional encryptor; defaults to app configuration.
    """
    asset.secrets = set_secret(
        asset.secrets,
        path,
        value,
        metadata=metadata,
        encryptor=encryptor,
    )
    return asset.secrets


def get_secret(
    secrets: dict[str, Any] | None,
    path: str | tuple[str, ...] | list[str],
    *,
    encryptor: SecretsEncryptor | None = None,
) -> str:
    """Decrypt and return a secret value from ``path``.

    :param secrets: Secrets dictionary containing encrypted envelopes.
    :param path: Dot-separated path or sequence of keys to the encrypted value.
    :param encryptor: Optional encryptor; defaults to app configuration.
    :return: Decrypted plaintext value.
    """
    encryptor = encryptor or SecretsEncryptor.from_current_app()
    current: Any = secrets or {}
    for part in _path_parts(path):
        if not isinstance(current, dict) or part not in current:
            raise KeyError("Secret path does not exist.")
        current = current[part]
    return encryptor.decrypt(current)


def get_secret_paths(secrets: dict[str, Any] | None) -> list[str]:
    """Return sorted dot-separated paths to encrypted secret values.

    :param secrets: Secrets dictionary containing encrypted envelopes.
    :return: Secret paths without ciphertext or metadata values.
    """
    return [secret["path"] for secret in get_secret_overview(secrets)]


def get_secret_overview(
    secrets: dict[str, Any] | None,
) -> list[SecretOverview]:
    """Return safe information for listing stored secrets.

    :param secrets: Secrets dictionary containing encrypted envelopes.
    :return: Secret paths with optional expiry datetimes, without other metadata.
    """
    overview: list[SecretOverview] = []

    def _collect(value: Any, parts: list[str]) -> None:
        if not isinstance(value, dict):
            return
        if _CIPHERTEXT_FIELD in value:
            secret: SecretOverview = {"path": ".".join(parts)}
            expires_at = value.get("expires_at")
            if isinstance(expires_at, str):
                try:
                    parsed_expires_at = datetime.fromisoformat(
                        f"{expires_at[:-1]}+00:00"
                        if expires_at.endswith("Z")
                        else expires_at
                    )
                except ValueError:
                    pass
                else:
                    if (
                        parsed_expires_at.tzinfo is not None
                        and parsed_expires_at.utcoffset() is not None
                    ):
                        secret["expires_at"] = parsed_expires_at
            overview.append(secret)
            return
        for key, nested_value in value.items():
            _collect(nested_value, [*parts, key])

    _collect(secrets or {}, [])
    return sorted(overview, key=lambda secret: secret["path"])


def redact_secrets(secrets: dict[str, Any] | None) -> dict[str, Any]:
    """Return secrets metadata without ciphertext or plaintext values.

    :param secrets: Secrets dictionary to redact.
    :return: Copy with encrypted values replaced by safe metadata.
    """
    if not secrets:
        return {}

    def _redact(value: Any) -> Any:
        if isinstance(value, dict):
            if _CIPHERTEXT_FIELD in value:
                return {
                    "set": bool(value.get(_CIPHERTEXT_FIELD)),
                    **{
                        key: redacted_value
                        for key in (
                            "key_id",
                            "created_at",
                            "updated_at",
                            "expires_at",
                            "token_type",
                        )
                        if (redacted_value := value.get(key)) is not None
                    },
                }
            return {key: _redact(nested) for key, nested in value.items()}
        return value

    return _redact(secrets)


@dataclass(frozen=True, slots=True)
class TokenRefreshResult:
    """Provider-neutral result of refreshing token state.

    :param access_token: New access token, if the provider returned one.
    :param refresh_token: New refresh token, if it rotated.
    :param access_token_expires_at: Expiry timestamp for the access token.
    :param refresh_token_expires_at: Expiry timestamp for the refresh token.
    :param token_type: Token type metadata, for example ``Bearer``.
    :param metadata: Provider-specific non-secret metadata to preserve.
    """

    access_token: str | None = None
    refresh_token: str | None = None
    access_token_expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
    token_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def apply_token_refresh_result(
    secrets: dict[str, Any] | None,
    namespace: str,
    result: TokenRefreshResult,
    *,
    encryptor: SecretsEncryptor | None = None,
) -> dict[str, Any]:
    """Apply a provider-specific token refresh result to a secrets dictionary.

    If a token value is ``None``, only its metadata is updated. This supports
    providers whose refresh operation extends an existing token instead of
    returning a replacement token.

    :param secrets: Existing secrets dictionary, or ``None`` for a new one.
    :param namespace: Top-level provider or strategy namespace to update.
    :param result: Token values and metadata returned by a provider strategy.
    :param encryptor: Optional encryptor; defaults to app configuration.
    :return: Updated copy of the secrets dictionary.
    """
    encryptor = encryptor or SecretsEncryptor.from_current_app()
    updated = deepcopy(secrets or {})
    provider_state = updated.setdefault(namespace, {})
    if not isinstance(provider_state, dict):
        raise ValueError(f"Secret namespace {namespace} conflicts with a non-object.")

    token_updates = {
        "access_token": (
            result.access_token,
            result.access_token_expires_at,
        ),
        "refresh_token": (
            result.refresh_token,
            result.refresh_token_expires_at,
        ),
    }
    for token_name, (token_value, expires_at) in token_updates.items():
        metadata = {
            key: value
            for key, value in {
                "expires_at": as_utc_isoformat(expires_at),
                "token_type": result.token_type,
            }.items()
            if value is not None
        }
        if token_value is not None:
            provider_state[token_name] = encryptor.encrypt(token_value)
        if metadata and token_name in provider_state:
            provider_state[token_name].update(metadata)
            provider_state[token_name]["updated_at"] = as_utc_isoformat(server_now())

    if result.metadata:
        provider_state.setdefault("metadata", {}).update(result.metadata)
    return updated
