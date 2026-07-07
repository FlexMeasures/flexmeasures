"""
Tests for the JSON attributes editor button and modal.

Checks that the "Edit attributes" button is present in the edit side-panels
of sensor, asset-properties, and account pages for users who have update rights.
"""

from __future__ import annotations

import re
from datetime import datetime

from flask import url_for
from flask_login import current_user

from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.utils.time_utils import naturalized_datetime_str


EDITOR_BUTTON_MARKER = b"Open editor"
EDITOR_MODAL_MARKER = b"jsonAttributesModal"
SECRET_EXPIRES_AT = "2026-06-11T12:00:00+00:00"
SECRET_METADATA_MARKERS = (
    b"sensitive-ciphertext",
    b"sensitive-key-id",
    b"sensitive-created-at",
    b"sensitive-updated-at",
    b"sensitive-token-type",
    b"sensitive-provider-metadata",
)


def find_stored_secrets_table(response_data: bytes) -> bytes:
    table = re.search(
        rb"<table[^>]*>(?:(?!</table>)[\s\S])*?Stored secret"
        rb"(?:(?!</table>)[\s\S])*</table>",
        response_data,
    )
    assert table is not None
    return table.group()


def assert_secret_metadata_is_safely_rendered(response_data: bytes) -> None:
    stored_secrets_table = find_stored_secrets_table(response_data)

    def find_secret_row(path: bytes) -> re.Match[bytes] | None:
        return re.search(
            rb"<tr[^>]*>(?:(?!</tr>)[\s\S])*?"
            + re.escape(path)
            + rb"(?:(?!</tr>)[\s\S])*</tr>",
            stored_secrets_table,
        )

    expiring_secret_row = find_secret_row(b"platform.access_token")
    secret_without_expiry_row = find_secret_row(b"platform.refresh_token")
    assert expiring_secret_row is not None
    assert secret_without_expiry_row is not None

    human_expiry = naturalized_datetime_str(
        datetime.fromisoformat(SECRET_EXPIRES_AT)
    ).encode()
    expiry_title = f'title="{SECRET_EXPIRES_AT}"'.encode()
    assert b"Expires" in stored_secrets_table
    assert human_expiry in expiring_secret_row.group()
    assert human_expiry not in secret_without_expiry_row.group()
    assert expiry_title in expiring_secret_row.group()
    assert expiry_title not in secret_without_expiry_row.group()
    for marker in SECRET_METADATA_MARKERS:
        assert marker not in response_data


def secret_test_data() -> dict:
    return {
        "platform": {
            "access_token": {
                "ciphertext": "sensitive-ciphertext",
                "key_id": "sensitive-key-id",
                "created_at": "sensitive-created-at",
                "updated_at": "sensitive-updated-at",
                "expires_at": SECRET_EXPIRES_AT,
                "token_type": "sensitive-token-type",
                "provider_metadata": "sensitive-provider-metadata",
            },
            "refresh_token": {
                "ciphertext": "another-sensitive-ciphertext",
            },
        }
    }


# ---------------------------------------------------------------------------
# Sensor page
# ---------------------------------------------------------------------------


def test_sensor_page_shows_attributes_editor_for_admin(
    db, client, setup_assets, as_admin
):
    """An admin user sees the 'Edit attributes' button on the sensor page."""
    user = find_user_by_email("flexmeasures-admin@seita.nl")
    sensor = user.account.generic_assets[0].sensors[0]

    response = client.get(
        url_for("SensorUI:get", id=sensor.id),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert EDITOR_BUTTON_MARKER in response.data
    assert EDITOR_MODAL_MARKER in response.data


def test_sensor_page_no_attributes_editor_for_non_admin(
    db, client, setup_assets, as_prosumer_user1
):
    """A plain prosumer (no update rights on sensors) does NOT see the editor button."""
    user = find_user_by_email("test_prosumer_user@seita.nl")
    sensor = user.account.generic_assets[0].sensors[0]

    response = client.get(
        url_for("SensorUI:get", id=sensor.id),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert EDITOR_BUTTON_MARKER not in response.data
    assert EDITOR_MODAL_MARKER not in response.data


# ---------------------------------------------------------------------------
# Asset-properties page
# ---------------------------------------------------------------------------


def test_asset_properties_page_shows_attributes_editor(
    db, client, setup_assets, as_admin
):
    """An admin user sees the 'Edit attributes' button on the asset-properties page."""
    user = find_user_by_email("flexmeasures-admin@seita.nl")
    asset = user.account.generic_assets[0]

    response = client.get(
        url_for("AssetCrudUI:properties", id=asset.id),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert EDITOR_BUTTON_MARKER in response.data
    assert EDITOR_MODAL_MARKER in response.data


def test_asset_properties_page_shows_secret_paths_without_values(
    db, client, setup_assets, as_admin
):
    user = find_user_by_email("flexmeasures-admin@seita.nl")
    asset = user.account.generic_assets[0]
    original_secrets = asset.secrets
    asset.secrets = secret_test_data()
    db.session.commit()

    try:
        response = client.get(
            url_for("AssetCrudUI:properties", id=asset.id),
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Stored secret" in response.data
        assert b"platform.access_token" in response.data
        assert b"platform.refresh_token" in response.data
        assert_secret_metadata_is_safely_rendered(response.data)
    finally:
        asset.secrets = original_secrets
        db.session.commit()


def test_asset_properties_page_omits_expires_column_without_expiry_metadata(
    db, client, setup_assets, as_admin
):
    user = find_user_by_email("flexmeasures-admin@seita.nl")
    asset = user.account.generic_assets[0]
    original_secrets = asset.secrets
    asset.secrets = {
        "platform": {
            "access_token": {"ciphertext": "sensitive-ciphertext"},
            "refresh_token": {"ciphertext": "another-sensitive-ciphertext"},
        }
    }
    db.session.commit()

    try:
        response = client.get(
            url_for("AssetCrudUI:properties", id=asset.id),
            follow_redirects=True,
        )
        assert response.status_code == 200
        stored_secrets_table = find_stored_secrets_table(response.data)
        assert b"platform.access_token" in stored_secrets_table
        assert b"platform.refresh_token" in stored_secrets_table
        assert b"Expires" not in stored_secrets_table
        assert b"sensitive-ciphertext" not in response.data
        assert b"another-sensitive-ciphertext" not in response.data
    finally:
        asset.secrets = original_secrets
        db.session.commit()


# ---------------------------------------------------------------------------
# Account page
# ---------------------------------------------------------------------------


def test_account_page_shows_attributes_editor(db, client, as_prosumer_user1):
    """The account page shows the 'Edit attributes' button for a logged-in user."""
    response = client.get(
        url_for("AccountCrudUI:get", account_id=current_user.account_id),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert EDITOR_BUTTON_MARKER in response.data
    assert EDITOR_MODAL_MARKER in response.data


def test_account_page_shows_secret_paths_without_values(db, client, as_prosumer_user1):
    account = current_user.account
    original_secrets = account.secrets
    account.secrets = secret_test_data()
    db.session.commit()

    try:
        response = client.get(
            url_for("AccountCrudUI:get", account_id=account.id),
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Stored secret" in response.data
        assert b"platform.access_token" in response.data
        assert b"platform.refresh_token" in response.data
        assert_secret_metadata_is_safely_rendered(response.data)
    finally:
        account.secrets = original_secrets
        db.session.commit()
