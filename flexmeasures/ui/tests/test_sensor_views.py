"""
Tests for the Sensor UI view (SensorUI).

The sensor page at /sensors/<id> renders sensor details and optional
Forecast and Annotate side panels. These tests verify:

- Basic access and 404 behaviour
- Forecast and Annotate panel visibility gated on ``create-children`` permission
- Forecast button enabled/disabled state based on available data range
- Guard that ``get_timerange`` is NOT called for users without permission
"""

from datetime import datetime, timedelta, timezone
import re
from unittest.mock import patch

import pytest
from flask import url_for

from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.ui.tests.utils import login, logout
from flexmeasures.ui.views.sensors import MAX_NAMED_FIELD_GROUPS


@pytest.fixture(scope="function")
def as_supplier_user(client):
    """
    Login the default test supplier user (from the *Supplier* account) and log
    them out afterwards.  The Supplier account does not own the Prosumer
    account's sensors, so this user lacks ``create-children`` permission on
    those sensors.
    """
    login(client, "test_supplier_user_4@seita.nl", "testtest")
    yield
    logout(client)


def _get_prosumer_sensor(db):
    """Return the first sensor that belongs to the first Prosumer asset."""
    user = find_user_by_email("test_prosumer_user@seita.nl")
    sensor = user.account.generic_assets[0].sensors[0]
    db.session.expunge(user)
    return sensor


# ---------------------------------------------------------------------------
# Basic page access
# ---------------------------------------------------------------------------


def test_sensor_page_loads(db, client, setup_assets, as_prosumer_user1):
    """Sensor page returns HTTP 200 for a logged-in owner-account user."""
    sensor = _get_prosumer_sensor(db)
    response = client.get(url_for("SensorUI:get", id=sensor.id), follow_redirects=True)
    assert response.status_code == 200
    assert sensor.name.encode() in response.data
    assert b'id="fullBeliefInfoToggle"' in response.data
    assert b"Full belief info" in response.data


def test_sensor_page_preselects_source(db, client, setup_assets, as_prosumer_user1):
    """The source query parameter is passed on to the page, for the statistics panel."""
    sensor = _get_prosumer_sensor(db)
    response = client.get(
        url_for("SensorUI:get", id=sensor.id, source=42), follow_redirects=True
    )
    assert response.status_code == 200
    assert b'data-preselected-source-id="42"' in response.data


def test_sensor_page_lists_feeding_automations(
    db, client, setup_assets, as_prosumer_user1
):
    """Automations that write data to the sensor are listed on its page."""
    from flexmeasures.data.models.automations import Automation

    sensor = _get_prosumer_sensor(db)
    response = client.get(url_for("SensorUI:get", id=sensor.id), follow_redirects=True)
    assert b"Bihourly forecasts" not in response.data

    with (
        patch(
            "flexmeasures.ui.views.sensors.get_automations_feeding_sensor",
            return_value=[
                Automation(
                    id=1,
                    asset_id=sensor.generic_asset_id,
                    name="Bihourly forecasts",
                    cronstr="0 */2 * * *",
                    active=True,
                )
            ],
        ),
        patch("flexmeasures.ui.views.sensors.user_can_read", return_value=True),
    ):
        response = client.get(
            url_for("SensorUI:get", id=sensor.id), follow_redirects=True
        )
    assert response.status_code == 200
    assert b"Bihourly forecasts" in response.data
    assert b"Every 2 hours" in response.data


def test_sensor_page_requires_login(client, setup_assets):
    """Unauthenticated requests are redirected to the login page."""
    response = client.get(url_for("SensorUI:get", id=1), follow_redirects=True)
    assert b"Please log in" in response.data


def test_sensor_page_404_for_nonexistent_sensor(db, client, as_prosumer_user1):
    """Requesting a non-existent sensor ID returns a 404."""
    response = client.get(url_for("SensorUI:get", id=999999), follow_redirects=True)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Forecast and Annotate panels – visibility based on permissions
# ---------------------------------------------------------------------------


def test_forecast_and_annotate_panels_visible_for_account_member(
    db, client, setup_assets, as_prosumer_user1
):
    """
    The Forecast and Annotate panels are rendered for a user who belongs to
    the account that owns the sensor (Sensor ACL grants ``create-children``
    to every member of the owning account).
    """
    sensor = _get_prosumer_sensor(db)
    response = client.get(url_for("SensorUI:get", id=sensor.id), follow_redirects=True)
    assert response.status_code == 200
    assert b"Trigger forecast" in response.data
    assert b'id="annotateForm"' in response.data
    assert b"pick the select tool above the chart" in response.data
    assert b'id="annotationStart"' in response.data
    assert b'id="annotationEnd"' in response.data
    assert b"firstAvailableEventStartForForecastTraining" in response.data
    assert (
        b"firstAvailableEventStartForForecastTraining = e.detail.firstEventStart"
        in response.data
    )
    assert b'"train-start"' in response.data


def test_forecast_and_annotate_panels_visible_for_admin(
    db, client, setup_assets, as_admin
):
    """Admin users bypass ACL and see both the Forecast and Annotate panels."""
    sensor = _get_prosumer_sensor(db)
    response = client.get(url_for("SensorUI:get", id=sensor.id), follow_redirects=True)
    assert response.status_code == 200
    assert b"Trigger forecast" in response.data
    assert b'id="annotateForm"' in response.data


def test_sensor_page_forbidden_for_other_account(
    db, client, setup_assets, as_supplier_user
):
    """
    A user from another account cannot read this sensor page.
    """
    sensor = _get_prosumer_sensor(db)
    response = client.get(url_for("SensorUI:get", id=sensor.id), follow_redirects=True)
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Forecast button state – enabled vs. disabled
# ---------------------------------------------------------------------------


def test_forecast_button_disabled_with_insufficient_data(
    db, client, setup_assets, as_prosumer_user1
):
    """
    The forecast button is disabled and an explanatory message is shown when
    the sensor has fewer than two days of historical data.

    ``setup_assets`` populates each sensor with one day of beliefs
    (2015-01-01 at 15-minute resolution), which is below the 2-day threshold.
    """
    sensor = _get_prosumer_sensor(db)
    response = client.get(url_for("SensorUI:get", id=sensor.id), follow_redirects=True)
    assert response.status_code == 200
    assert b"Trigger forecast" in response.data
    # The enabled trigger button is present in the DOM but hidden (d-none).
    # The disabled-state button wrapper (forecastButtonDisabled) is visible.
    assert b'class="mb-3 d-none" id="forecastStartContainer"' in response.data
    assert b'class="mb-3" id="forecastNoDataMessage"' in response.data


def test_forecast_button_enabled_with_sufficient_data(
    db, client, setup_assets, as_prosumer_user1
):
    """
    The forecast button is enabled and the JS polling code is injected when
    the sensor has at least two days of historical data.

    ``get_timerange`` is patched to return a two-day span.
    """
    sensor = _get_prosumer_sensor(db)
    t0 = datetime(2015, 1, 1, tzinfo=timezone.utc)
    t2 = t0 + timedelta(days=2)

    with patch(
        "flexmeasures.ui.views.sensors.get_timerange",
        return_value=(t0, t2),
    ):
        response = client.get(
            url_for("SensorUI:get", id=sensor.id), follow_redirects=True
        )

    assert response.status_code == 200
    # The enabled trigger button is visible (no d-none on its container) and
    # the "not enough data" message is hidden.
    assert b'class="mb-3" id="forecastStartContainer"' in response.data
    assert b'class="mb-3 d-none" id="forecastNoDataMessage"' in response.data


def test_forecast_boundary_just_under_two_days(
    db, client, setup_assets, as_prosumer_user1
):
    """
    A data span of exactly two days minus one second does NOT pass the
    ``>= timedelta(days=2)`` threshold.
    """
    sensor = _get_prosumer_sensor(db)
    t0 = datetime(2015, 1, 1, tzinfo=timezone.utc)
    t_short = t0 + timedelta(days=2) - timedelta(seconds=1)

    with patch(
        "flexmeasures.ui.views.sensors.get_timerange",
        return_value=(t0, t_short),
    ):
        response = client.get(
            url_for("SensorUI:get", id=sensor.id), follow_redirects=True
        )

    assert response.status_code == 200
    # Just under two days: enabled form is hidden, no-data message is visible.
    assert b'class="mb-3 d-none" id="forecastStartContainer"' in response.data
    assert b'class="mb-3" id="forecastNoDataMessage"' in response.data


# ---------------------------------------------------------------------------
# Guard: get_timerange is NOT called when user has no permission
# ---------------------------------------------------------------------------


def test_get_timerange_not_called_without_permission(
    db, client, setup_assets, as_supplier_user
):
    """
    ``get_timerange`` must not run when sensor reading is denied.
    """
    sensor = _get_prosumer_sensor(db)

    with patch("flexmeasures.ui.views.sensors.get_timerange") as mock_get_timerange:
        response = client.get(
            url_for("SensorUI:get", id=sensor.id), follow_redirects=True
        )

    assert response.status_code == 403
    mock_get_timerange.assert_not_called()


# ---------------------------------------------------------------------------
# Deleting a sensor that flex-config fields refer to
# ---------------------------------------------------------------------------


def _fetch_deletion_notes(client, sensor) -> tuple[str, str]:
    """Fetch what the sensor page tells the user once they click to delete the sensor."""
    response = client.get(url_for("SensorUI:deletion_notes", id=sensor.id))
    assert response.status_code == 200
    return response.json["confirmation-note"], response.json["toast"]


def test_sensor_page_names_fields_its_deletion_leaves_without_sensor(
    db, client, setup_assets, setup_accounts, setup_generic_asset_types, as_admin
):
    """Before deleting a sensor, the user is told which fields will need a new sensor, and afterwards gets links to them."""
    sensor = _get_prosumer_sensor(db)
    asset = GenericAsset(
        name="asset-referring-to-a-sensor-to-delete",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Prosumer"],
        flex_context={
            "production-price": {"sensor": sensor.id, "default": "10 EUR/MWh"},
            "consumption-price": {"sensor": sensor.id},
        },
    )
    db.session.add(asset)
    db.session.commit()

    note, toast = _fetch_deletion_notes(client, sensor)

    assert f"- {asset.name}, flex-context: production-price" in note
    # A reference holding only the sensor is removed, so it needs no new sensor.
    assert "consumption-price" not in note
    assert (
        url_for(
            "AssetCrudUI:context", id=asset.id, flex_context_field="production-price"
        )
        in toast
    )
    assert "consumption-price" not in toast


def test_sensor_page_only_counts_fields_on_assets_the_user_cannot_see(
    db, client, setup_assets, setup_accounts, setup_generic_asset_types
):
    """A sensor can be referenced from another organisation's assets, which the user deleting it is told about without naming them."""
    sensor = _get_prosumer_sensor(db)
    asset = GenericAsset(
        name="other-organisation-asset-referring-to-a-sensor-to-delete",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Supplier"],
        flex_context={
            "production-price": {"sensor": sensor.id, "default": "10 EUR/MWh"}
        },
    )
    db.session.add(asset)
    db.session.commit()

    login(client, "test_prosumer_user_2@seita.nl", "testtest")
    note, toast = _fetch_deletion_notes(client, sensor)
    logout(client)

    assert "- fields on 1 asset you cannot see" in note
    assert asset.name not in note
    assert asset.name not in toast
    assert f"/assets/{asset.id}/" not in toast


def test_sensor_page_does_not_name_fields_whose_sensor_was_deleted_before(
    db, client, setup_assets, setup_accounts, setup_generic_asset_types, as_admin
):
    """A field that lost an earlier sensor already needs a new one, and deleting this sensor does not change that."""
    sensor = _get_prosumer_sensor(db)
    asset = GenericAsset(
        name="asset-with-a-field-whose-sensor-was-deleted-before",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Prosumer"],
        flex_context={
            "production-price": {"sensor": sensor.id, "default": "10 EUR/MWh"},
            "consumption-price": {"sensor": None, "default": "20 EUR/MWh"},
        },
    )
    db.session.add(asset)
    db.session.commit()

    note, _ = _fetch_deletion_notes(client, sensor)
    assert f"- {asset.name}, flex-context: production-price\n" in note + "\n"


def test_sensor_deletion_toast_leaves_out_the_page_it_moves_on_to(
    db, client, setup_assets, setup_accounts, setup_generic_asset_types, as_admin
):
    """The sensor's own asset shows its own toast after the deletion, so the deletion's toast does not repeat it."""
    sensor = _get_prosumer_sensor(db)
    own_asset = db.session.get(GenericAsset, sensor.generic_asset_id)
    original_flex_model = own_asset.flex_model
    own_asset.flex_model = {"soc-min": {"sensor": sensor.id, "default": "1 kWh"}}
    db.session.commit()

    note, toast = _fetch_deletion_notes(client, sensor)
    own_asset.flex_model = original_flex_model
    db.session.commit()
    assert f"- {own_asset.name}, flex-model: soc-min" in note
    assert url_for("AssetCrudUI:properties", id=own_asset.id) not in toast


def test_sensor_page_names_only_the_first_few_assets_whose_fields_need_a_new_sensor(
    db, client, setup_assets, setup_accounts, setup_generic_asset_types, as_admin
):
    """A shared sensor, such as a price, can be referenced by many assets, which the confirmation and toast do not list in full."""
    sensor = _get_prosumer_sensor(db)
    for i in range(MAX_NAMED_FIELD_GROUPS + 2):
        db.session.add(
            GenericAsset(
                name=f"site-{i}-sharing-a-price-sensor-to-delete",
                generic_asset_type=setup_generic_asset_types["battery"],
                owner=setup_accounts["Prosumer"],
                flex_context={
                    "consumption-price": {"sensor": sensor.id, "default": "20 EUR/MWh"}
                },
            )
        )
    db.session.commit()

    note, toast = _fetch_deletion_notes(client, sensor)

    named_lines = [
        line
        for line in note.splitlines()
        if line.startswith("- ") and not line.startswith("- and ")
    ]
    assert len(named_lines) == MAX_NAMED_FIELD_GROUPS
    assert re.search(r"^- and \d+ more$", note, re.MULTILINE)
    assert toast.count("<a href=") == MAX_NAMED_FIELD_GROUPS
    assert re.search(r"; and \d+ more\.", toast)


def test_sensor_page_leaves_the_search_for_fields_to_the_delete_button(
    db, client, setup_assets, as_admin
):
    """Finding the fields that deleting a sensor leaves without one searches every asset, so viewing the sensor page does not."""
    sensor = _get_prosumer_sensor(db)
    with patch(
        "flexmeasures.ui.views.sensors.flex_config_fields_left_without_sensor",
        return_value=[],
    ) as search:
        response = client.get(url_for("SensorUI:get", id=sensor.id))
        assert response.status_code == 200
        search.assert_not_called()
        _fetch_deletion_notes(client, sensor)
        search.assert_called_once_with(sensor.id)


def test_sensor_deletion_notes_are_only_for_users_who_may_delete_the_sensor(
    db, client, setup_generic_asset_types, as_supplier_user
):
    """Who may read a sensor but not delete it, such as one on a public asset, is not told which fields deleting it would affect."""
    public_asset = GenericAsset(
        name="public-asset-with-a-sensor-only-an-admin-may-delete",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=None,
    )
    sensor = Sensor(name="public-sensor", generic_asset=public_asset, unit="kW")
    db.session.add_all([public_asset, sensor])
    db.session.commit()

    assert client.get(url_for("SensorUI:get", id=sensor.id)).status_code == 200
    response = client.get(url_for("SensorUI:deletion_notes", id=sensor.id))
    assert response.status_code == 403


def test_sensor_deletion_notes_are_for_whoever_may_delete_the_sensor(
    db, client, setup_accounts, setup_generic_asset_types, as_prosumer_user1
):
    """A member without a role may delete a sensor that holds no data, so is told which fields deleting it would affect, as an account admin is."""
    asset = GenericAsset(
        name="asset-with-a-sensor-a-member-may-delete",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Prosumer"],
    )
    sensor = Sensor(name="sensor-without-data", generic_asset=asset, unit="EUR/MWh")
    db.session.add_all([asset, sensor])
    db.session.flush()
    site = GenericAsset(
        name="site-referring-to-a-sensor-a-member-may-delete",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Prosumer"],
        flex_context={
            "consumption-price": {"sensor": sensor.id, "default": "20 EUR/MWh"}
        },
    )
    db.session.add(site)
    db.session.commit()

    response = client.get(url_for("SensorUI:get", id=sensor.id))
    assert b'id="delete-sensor-button"' in response.data
    note, _ = _fetch_deletion_notes(client, sensor)
    assert f"- {site.name}, flex-context: consumption-price" in note


def test_sensor_deletion_notes_need_a_sensor_id(client, as_admin):
    """An id that is not a number names no sensor."""
    assert client.get("/sensors/not-a-number/deletion-notes").status_code == 404
