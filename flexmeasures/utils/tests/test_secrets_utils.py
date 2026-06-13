from datetime import datetime, timezone

import pytest

from flexmeasures.utils.secrets_utils import (
    SecretsDecryptionError,
    SecretsEncryptor,
    InvalidSecretsEncryptionKey,
    TokenRefreshResult,
    apply_token_refresh_result,
    derive_fernet_key,
    get_secret,
    redact_secrets,
    set_secret,
)


def test_derive_fernet_key_accepts_non_fernet_secret():
    key = derive_fernet_key("not-a-fernet-key")

    assert isinstance(key, bytes)
    assert len(key) == 44


def test_encrypt_decrypt_and_redact_secret():
    encryptor = SecretsEncryptor("test-master-key", key_id="test-key")
    secrets = set_secret(
        {},
        "connection.refresh_token",
        "refresh-token-value",
        encryptor=encryptor,
        metadata={"expires_at": "2026-06-11T12:00:00+00:00"},
    )

    envelope = secrets["connection"]["refresh_token"]
    assert envelope["ciphertext"] != "refresh-token-value"
    assert get_secret(secrets, "connection.refresh_token", encryptor=encryptor) == (
        "refresh-token-value"
    )
    assert redact_secrets(secrets) == {
        "connection": {
            "refresh_token": {
                "set": True,
                "key_id": "test-key",
                "created_at": envelope["created_at"],
                "updated_at": envelope["updated_at"],
                "expires_at": "2026-06-11T12:00:00+00:00",
            }
        }
    }


def test_decrypt_rejects_wrong_key():
    secrets = set_secret(
        {},
        "connection.password",
        "secret",
        encryptor=SecretsEncryptor("first-key"),
    )

    with pytest.raises(SecretsDecryptionError):
        get_secret(
            secrets,
            "connection.password",
            encryptor=SecretsEncryptor("second-key"),
        )


def test_from_current_app_falls_back_to_secret_key_outside_production(app):
    app.config["FLEXMEASURES_ENV"] = "testing"
    app.config["FLEXMEASURES_SECRETS_ENCRYPTION_KEY"] = None
    app.config["SECRET_KEY"] = "testing-secret-key"

    encryptor = SecretsEncryptor.from_current_app()

    assert encryptor.encryption_key == "testing-secret-key"


def test_from_current_app_requires_dedicated_key_in_production(app):
    app.config["FLEXMEASURES_ENV"] = "production"
    app.config["FLEXMEASURES_SECRETS_ENCRYPTION_KEY"] = None
    app.config["SECRET_KEY"] = "production-secret-key"

    with pytest.raises(
        InvalidSecretsEncryptionKey,
        match="FLEXMEASURES_SECRETS_ENCRYPTION_KEY is required in production",
    ):
        SecretsEncryptor.from_current_app()


def test_apply_token_refresh_result_can_update_tokens_and_metadata():
    encryptor = SecretsEncryptor("token-key")
    result = TokenRefreshResult(
        access_token="access-1",
        refresh_token="refresh-1",
        access_token_expires_at=datetime(2026, 6, 11, 12, 5, tzinfo=timezone.utc),
        refresh_token_expires_at=datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc),
        token_type="Bearer",
        metadata={"scope": "read write"},
    )

    secrets = apply_token_refresh_result(
        {},
        "platform",
        result,
        encryptor=encryptor,
    )

    assert get_secret(secrets, "platform.access_token", encryptor=encryptor) == (
        "access-1"
    )
    assert get_secret(secrets, "platform.refresh_token", encryptor=encryptor) == (
        "refresh-1"
    )
    assert secrets["platform"]["access_token"]["expires_at"] == (
        "2026-06-11T12:05:00+00:00"
    )
    assert secrets["platform"]["refresh_token"]["expires_at"] == (
        "2026-06-25T12:00:00+00:00"
    )
    assert secrets["platform"]["metadata"] == {"scope": "read write"}


def test_apply_token_refresh_result_can_extend_existing_access_token():
    encryptor = SecretsEncryptor("token-key")
    secrets = apply_token_refresh_result(
        {},
        "platform",
        TokenRefreshResult(access_token="existing-access-token"),
        encryptor=encryptor,
    )
    original_ciphertext = secrets["platform"]["access_token"]["ciphertext"]

    secrets = apply_token_refresh_result(
        secrets,
        "platform",
        TokenRefreshResult(
            access_token=None,
            access_token_expires_at=datetime(2026, 6, 11, 12, 10, tzinfo=timezone.utc),
        ),
        encryptor=encryptor,
    )

    assert secrets["platform"]["access_token"]["ciphertext"] == original_ciphertext
    assert get_secret(secrets, "platform.access_token", encryptor=encryptor) == (
        "existing-access-token"
    )
    assert secrets["platform"]["access_token"]["expires_at"] == (
        "2026-06-11T12:10:00+00:00"
    )
