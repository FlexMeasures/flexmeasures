from datetime import datetime, timezone

import pytest

from flexmeasures.utils.secrets_utils import (
    SecretsDecryptionError,
    SecretsEncryptor,
    InvalidSecretsEncryptionKey,
    TokenRefreshResult,
    apply_token_refresh_result,
    delete_secret,
    derive_fernet_key,
    format_keyring_config_help,
    get_secret,
    get_secret_overview,
    get_secret_paths,
    redact_secrets,
    set_secret,
    set_totp_secrets,
    store_account_secret,
    store_asset_secret,
)


def test_derive_fernet_key_accepts_non_fernet_secret():
    key = derive_fernet_key("not-a-fernet-key")

    assert isinstance(key, bytes)
    assert len(key) == 44


def test_encrypt_decrypt_and_redact_secret():
    encryptor = SecretsEncryptor({"test-key": "test-master-key"}, key_id="test-key")
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


def test_store_account_secret_updates_account_secrets(setup_accounts):
    encryptor = SecretsEncryptor({"1": "test-master-key"})
    account = setup_accounts["Prosumer"]

    store_account_secret(
        account,
        "platform.refresh_token",
        "refresh-token-value",
        metadata={"expires_at": "2026-06-11T12:00:00+00:00"},
        encryptor=encryptor,
    )

    envelope = account.secrets["platform"]["refresh_token"]
    assert envelope["ciphertext"] != "refresh-token-value"
    assert envelope["expires_at"] == "2026-06-11T12:00:00+00:00"
    assert get_secret(
        account.secrets, "platform.refresh_token", encryptor=encryptor
    ) == ("refresh-token-value")


def test_store_asset_secret_updates_asset_secrets(setup_generic_assets):
    encryptor = SecretsEncryptor({"1": "test-master-key"})
    asset = setup_generic_assets["test_battery"]

    store_asset_secret(
        asset,
        "platform.password",
        "password-value",
        encryptor=encryptor,
    )

    envelope = asset.secrets["platform"]["password"]
    assert envelope["ciphertext"] != "password-value"
    assert get_secret(asset.secrets, "platform.password", encryptor=encryptor) == (
        "password-value"
    )


def test_decrypt_rejects_wrong_key():
    secrets = set_secret(
        {},
        "connection.password",
        "secret",
        encryptor=SecretsEncryptor({"1": "first-key"}),
    )

    with pytest.raises(SecretsDecryptionError):
        get_secret(
            secrets,
            "connection.password",
            encryptor=SecretsEncryptor({"1": "second-key"}),
        )


def test_delete_secret_removes_empty_parent_dicts():
    secrets = {
        "platform": {
            "access_token": {"ciphertext": "access"},
            "refresh_token": {"ciphertext": "refresh"},
        }
    }

    secrets = delete_secret(secrets, "platform.access_token")
    assert secrets == {"platform": {"refresh_token": {"ciphertext": "refresh"}}}

    secrets = delete_secret(secrets, "platform.refresh_token")
    assert secrets == {}


def test_delete_secret_rejects_missing_path():
    secrets = {"platform": {"access_token": {"ciphertext": "access"}}}

    with pytest.raises(KeyError, match="Secret path does not exist"):
        delete_secret(secrets, "platform.refresh_token")


def test_get_secret_paths_returns_only_encrypted_value_paths():
    secrets = {
        "platform": {
            "access_token": {"ciphertext": "access"},
            "metadata": {"scope": "read"},
            "nested": {
                "password": {"ciphertext": "password"},
            },
        }
    }

    assert get_secret_paths(secrets) == [
        "platform.access_token",
        "platform.nested.password",
    ]


def test_get_secret_overview_returns_sorted_strictly_allowlisted_fields():
    secrets = {
        "platform": {
            "refresh_token": {
                "ciphertext": "refresh",
                "key_id": "key-id",
                "created_at": "2026-06-01T12:00:00+00:00",
                "updated_at": "2026-06-02T12:00:00+00:00",
                "token_type": "Bearer",
                "provider_metadata": {"scope": "read write"},
            },
            "access_token": {
                "ciphertext": "access",
                "expires_at": "2026-06-11T12:00:00+02:00",
                "unexpected": "must-not-be-exposed",
            },
        }
    }

    overview = get_secret_overview(secrets)

    assert overview == [
        {
            "path": "platform.access_token",
            "expires_at": datetime.fromisoformat("2026-06-11T12:00:00+02:00"),
        },
        {"path": "platform.refresh_token"},
    ]
    assert all(set(secret) <= {"path", "expires_at"} for secret in overview)


@pytest.mark.parametrize(
    ("expires_at", "expected"),
    [
        (
            "2026-06-11T12:00:00+02:00",
            datetime.fromisoformat("2026-06-11T12:00:00+02:00"),
        ),
        (
            "2026-06-11T10:00:00Z",
            datetime(2026, 6, 11, 10, tzinfo=timezone.utc),
        ),
    ],
)
def test_get_secret_overview_accepts_aware_iso_expiry_timestamps(expires_at, expected):
    secrets = {
        "platform": {
            "access_token": {
                "ciphertext": "access",
                "expires_at": expires_at,
            }
        }
    }

    overview = get_secret_overview(secrets)

    assert overview == [
        {
            "path": "platform.access_token",
            "expires_at": expected,
        }
    ]
    assert overview[0]["expires_at"].tzinfo is not None


@pytest.mark.parametrize(
    "expires_at",
    [
        "not-a-datetime",
        1781179200,
        None,
        "2026-06-11T12:00:00",
    ],
)
def test_get_secret_overview_omits_invalid_or_naive_expiry(expires_at):
    secrets = {
        "platform": {
            "access_token": {
                "ciphertext": "access",
                "expires_at": expires_at,
            }
        }
    }

    assert get_secret_overview(secrets) == [{"path": "platform.access_token"}]


def test_get_secret_paths_remains_backward_compatible_with_secret_overview():
    secrets = {
        "z": {"secret": {"ciphertext": "z", "expires_at": "invalid"}},
        "a": {
            "secret": {
                "ciphertext": "a",
                "expires_at": "2026-06-11T10:00:00Z",
            }
        },
    }

    assert get_secret_paths(secrets) == ["a.secret", "z.secret"]
    assert get_secret_paths(secrets) == [
        secret["path"] for secret in get_secret_overview(secrets)
    ]


def test_from_current_app_requires_keyring_outside_production(app):
    app.config["FLEXMEASURES_ENV"] = "testing"
    app.config["FLEXMEASURES_SECRETS_ENCRYPTION_KEYS"] = None
    app.config["SECRET_KEY"] = "testing-secret-key"

    with pytest.raises(
        InvalidSecretsEncryptionKey,
        match="No FLEXMEASURES_SECRETS_ENCRYPTION_KEYS set",
    ):
        SecretsEncryptor.from_current_app()


def test_set_secret_requires_configured_keyring(app):
    app.config["FLEXMEASURES_SECRETS_ENCRYPTION_KEYS"] = None

    with pytest.raises(
        InvalidSecretsEncryptionKey,
        match="key IDs to secret values",
    ):
        set_secret({}, "connection.password", "secret")


def test_format_keyring_config_help_mentions_setting_and_generator():
    help_text = format_keyring_config_help(
        "FLEXMEASURES_SECRETS_ENCRYPTION_KEYS",
        purpose="required before storing connection secrets",
    )

    assert "FLEXMEASURES_SECRETS_ENCRYPTION_KEYS" in help_text
    assert '{"1": "xxxxxxxxxxxxxxx"}' in help_text
    assert "python3 -c" in help_text
    assert "secrets.token_urlsafe" in help_text


def test_set_totp_secrets_reads_environment(app, monkeypatch):
    app.config["SECURITY_TOTP_SECRETS"] = None
    monkeypatch.setenv("SECURITY_TOTP_SECRETS", '{"1": "totp-secret"}')

    set_totp_secrets(app)

    assert app.config["SECURITY_TOTP_SECRETS"] == {"1": "totp-secret"}


def test_set_totp_secrets_reads_file(app, tmp_path):
    app.config["SECURITY_TOTP_SECRETS"] = None
    secret_file = tmp_path / "totp_secrets"
    secret_file.write_text('{"1": "totp-secret"}')

    set_totp_secrets(app, filename=str(secret_file))

    assert app.config["SECURITY_TOTP_SECRETS"] == {"1": "totp-secret"}


def test_from_current_app_uses_latest_key_from_keyring(app):
    app.config["FLEXMEASURES_ENV"] = "production"
    app.config["FLEXMEASURES_SECRETS_ENCRYPTION_KEYS"] = {
        "1": "old-secret-key",
        "2": "current-secret-key",
    }

    encryptor = SecretsEncryptor.from_current_app()

    assert encryptor.encryption_keys == {
        "1": "old-secret-key",
        "2": "current-secret-key",
    }
    assert encryptor.key_id == "2"


def test_from_current_app_uses_lexical_latest_key_from_keyring(app):
    app.config["FLEXMEASURES_ENV"] = "production"
    app.config["FLEXMEASURES_SECRETS_ENCRYPTION_KEYS"] = {
        "2026-01": "old-secret-key",
        "2026-06": "current-secret-key",
    }

    encryptor = SecretsEncryptor.from_current_app()

    assert encryptor.key_id == "2026-06"


def test_decrypt_uses_key_id_from_envelope():
    old_encryptor = SecretsEncryptor(
        {"1": "old-secret-key", "2": "current-secret-key"},
        key_id="1",
    )
    current_encryptor = SecretsEncryptor(
        {"1": "old-secret-key", "2": "current-secret-key"},
        key_id="2",
    )

    envelope = old_encryptor.encrypt("old-secret-value")

    assert current_encryptor.decrypt(envelope) == "old-secret-value"


def test_decrypt_raw_token_can_try_all_configured_keys():
    old_encryptor = SecretsEncryptor(
        {"1": "old-secret-key", "2": "current-secret-key"},
        key_id="1",
    )
    current_encryptor = SecretsEncryptor(
        {"1": "old-secret-key", "2": "current-secret-key"},
        key_id="2",
    )
    raw_token = old_encryptor.encrypt("old-secret-value")["ciphertext"]

    assert current_encryptor.decrypt(raw_token) == "old-secret-value"


def test_apply_token_refresh_result_can_update_tokens_and_metadata():
    encryptor = SecretsEncryptor({"1": "token-key"})
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
    encryptor = SecretsEncryptor({"1": "token-key"})
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
