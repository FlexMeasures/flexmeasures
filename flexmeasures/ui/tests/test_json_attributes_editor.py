"""
Tests for the JSON attributes editor button and modal.

Checks that the "Edit attributes" button is present in the edit side-panels
of sensor, asset-properties, and account pages for users who have update rights.
"""

from __future__ import annotations

from flask import url_for
from flask_login import current_user

from flexmeasures.data.services.users import find_user_by_email


EDITOR_BUTTON_MARKER = b"Edit attributes"
EDITOR_MODAL_MARKER = b"jsonAttributesModal"


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
