from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from flask import current_app

from flexmeasures.utils.time_utils import as_utc_isoformat, server_now


class SecretsError(Exception):
    """Raised when secret handling fails."""


class InvalidSecretsEncryptionKey(SecretsError):
    """Raised when a usable encryption key cannot be loaded."""


class SecretsDecryptionError(SecretsError):
    """Raised when a value cannot be decrypted."""


_KDF_OUTPUT_BYTES = 32
_KDF_INFO = b"flexmeasures:connection-secrets:v1"
_CIPHERTEXT_FIELD = "ciphertext"


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

    :param encryption_key: Master key material used to derive the Fernet key.
    :param key_id: Identifier stored with encrypted values for future rotation.
    """

    encryption_key: str
    key_id: str = "default"

    @classmethod
    def from_current_app(cls) -> "SecretsEncryptor":
        """Create an encryptor from Flask configuration.

        In production, ``FLEXMEASURES_SECRETS_ENCRYPTION_KEY`` is required. In
        other environments, ``SECRET_KEY`` may be used as a fallback.
        """
        encryption_key = current_app.config.get("FLEXMEASURES_SECRETS_ENCRYPTION_KEY")
        key_id = current_app.config.get(
            "FLEXMEASURES_SECRETS_ENCRYPTION_KEY_ID", "default"
        )
        if not encryption_key:
            if current_app.config.get("FLEXMEASURES_ENV") == "production":
                raise InvalidSecretsEncryptionKey(
                    "FLEXMEASURES_SECRETS_ENCRYPTION_KEY is required in production."
                )
            encryption_key = current_app.config.get("SECRET_KEY")
        if not isinstance(key_id, str) or not key_id.strip():
            raise InvalidSecretsEncryptionKey(
                "FLEXMEASURES_SECRETS_ENCRYPTION_KEY_ID must be non-empty."
            )
        return cls(encryption_key=encryption_key or "", key_id=key_id)

    @property
    def fernet(self) -> Fernet:
        """Fernet instance derived from the configured master key."""
        return Fernet(derive_fernet_key(self.encryption_key))

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
        try:
            raw = self.fernet.decrypt(token.encode("utf-8"))
        except InvalidToken as exc:
            raise SecretsDecryptionError("Invalid secret token.") from exc
        return raw.decode("utf-8")


def _path_parts(path: str | tuple[str, ...] | list[str]) -> list[str]:
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
