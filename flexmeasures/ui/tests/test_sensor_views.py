"""
Tests for the Sensor UI view (SensorUI).

The sensor page at /sensors/<id> renders sensor details and optionally
a "Create forecast" side panel.  These tests verify:

- Basic access and 404 behaviour
- "Create forecast" panel visibility gated on ``create-children`` permission
- Forecast button enabled/disabled state based on available data range
- Guard that ``get_timerange`` is NOT called for users without permission
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from flask import url_for

from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.ui.tests.utils import login, logout


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
    response = client.get(
        url_for("SensorUI:get", id=sensor.id), follow_redirects=True
    )
    assert response.status_code == 200
    assert sensor.name.encode() in response.data


def test_sensor_page_requires_login(client, setup_assets):
    """Unauthenticated requests are redirected to the login page."""
    response = client.get(url_for("SensorUI:get", id=1), follow_redirects=True)
    assert b"Please log in" in response.data


def test_sensor_page_404_for_nonexistent_sensor(db, client, as_prosumer_user1):
    """Requesting a non-existent sensor ID returns a 404."""
    response = client.get(
        url_for("SensorUI:get", id=999999), follow_redirects=True
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# "Create forecast" panel – visibility based on permissions
# ---------------------------------------------------------------------------


def test_create_forecast_panel_visible_for_account_member(
    db, client, setup_assets, as_prosumer_user1
):
    """
    The "Create forecast" panel is rendered for a user who belongs to the
    account that owns the sensor (Sensor ACL grants ``create-children`` to
    every member of the owning account).
    """
    sensor = _get_prosumer_sensor(db)
    response = client.get(
        url_for("SensorUI:get", id=sensor.id), follow_redirects=True
    )
    assert response.status_code == 200
    assert b"Create forecast" in response.data


def test_create_forecast_panel_visible_for_admin(
    db, client, setup_assets, as_admin
):
    """Admin users bypass ACL and also see the "Create forecast" panel."""
    sensor = _get_prosumer_sensor(db)
    response = client.get(
        url_for("SensorUI:get", id=sensor.id), follow_redirects=True
    )
    assert response.status_code == 200
    assert b"Create forecast" in response.data


def test_create_forecast_panel_hidden_for_other_account(
    db, client, setup_assets, as_supplier_user
):
    """
    A user from a different account (no ``create-children`` permission on the
    sensor) does not see the "Create forecast" panel at all.
    """
    sensor = _get_prosumer_sensor(db)
    response = client.get(
        url_for("SensorUI:get", id=sensor.id), follow_redirects=True
    )
    assert response.status_code == 200
    assert b"Create forecast" not in response.data


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
    response = client.get(
        url_for("SensorUI:get", id=sensor.id), follow_redirects=True
    )
    assert response.status_code == 200
    assert b"Create forecast" in response.data
    # The enabled button (identified by its unique id) is absent
    assert b"triggerForecastButton" not in response.data
    # The explanatory message is shown
    assert b"At least two days of sensor data are needed" in response.data


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
    assert b"triggerForecastButton" in response.data
    assert b"At least two days of sensor data are needed" not in response.data


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
    assert b"triggerForecastButton" not in response.data
    assert b"At least two days of sensor data are needed" in response.data


# ---------------------------------------------------------------------------
# Guard: get_timerange is NOT called when user has no permission
# ---------------------------------------------------------------------------


def test_get_timerange_not_called_without_permission(
    db, client, setup_assets, as_supplier_user
):
    """
    ``get_timerange`` must not be called when ``user_can_create_children``
    returns ``False`` — the view short-circuits to avoid an unnecessary DB query.
    """
    sensor = _get_prosumer_sensor(db)

    with patch(
        "flexmeasures.ui.views.sensors.get_timerange"
    ) as mock_get_timerange:
        response = client.get(
            url_for("SensorUI:get", id=sensor.id), follow_redirects=True
        )

    assert response.status_code == 200
    mock_get_timerange.assert_not_called()
