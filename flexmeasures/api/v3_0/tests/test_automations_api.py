"""Tests for the automations endpoints (GET /api/v3_0/assets/<id>/automations[/<automation_id>])."""

from __future__ import annotations

import pytest
from flask import url_for

from flexmeasures.data.models.automations import Automation


@pytest.fixture(scope="module")
def add_automations(db, add_battery_assets):
    battery = add_battery_assets["Test battery"]
    automations = [
        Automation(
            asset_id=battery.id,
            type="forecasts",
            name="Day-ahead forecasts",
            cronstr="0 6 * * *",
            active=True,
            parameters={"sensor": battery.sensors[0].id},
        ),
        Automation(
            asset_id=battery.id,
            type="forecasts",
            name="Intraday forecasts",
            cronstr="0 * * * *",
            active=False,
            parameters={"sensor": battery.sensors[0].id},
        ),
    ]
    db.session.add_all(automations)
    db.session.flush()
    return automations


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        (None, 401),  # not logged in
        ("test_prosumer_user@seita.nl", 200),  # same account
        ("test_dummy_user_3@seita.nl", 403),  # different account
    ],
    indirect=["requesting_user"],
)
def test_get_automations_auth(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
    expected_status_code,
):
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.get(
            url_for("AssetAPI:get_automations", id=battery.id),
        )
    assert response.status_code == expected_status_code


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automations(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.get(
            url_for("AssetAPI:get_automations", id=battery.id),
        )
    assert response.status_code == 200
    automations = response.json["automations"]
    assert len(automations) == 2
    day_ahead = next(a for a in automations if a["name"] == "Day-ahead forecasts")
    assert day_ahead["type"] == "forecasts"
    assert day_ahead["cronstr"] == "0 6 * * *"
    assert day_ahead["recurrence_description"] == "At 06:00 AM"
    assert day_ahead["active"] is True
    assert day_ahead["created_at"] is not None
    # generator and parameters are not listed
    assert "generator_id" not in day_ahead
    assert "generator" not in day_ahead
    assert "parameters" not in day_ahead


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automation_details(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    battery = add_battery_assets["Test battery"]
    automation = add_automations[0]
    with app.test_client() as client:
        response = client.get(
            url_for(
                "AssetAPI:get_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
        )
    assert response.status_code == 200
    assert response.json["name"] == "Day-ahead forecasts"
    assert response.json["parameters"] == {"sensor": battery.sensors[0].id}
    assert response.json["job_stats"] == {}  # this automation has not queued any jobs


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automation_of_other_asset(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    """Requesting an automation via an asset it does not belong to should return 404."""
    other_asset = add_battery_assets["Test small battery"]
    automation = add_automations[0]
    with app.test_client() as client:
        response = client.get(
            url_for(
                "AssetAPI:get_automation",
                id=other_asset.id,
                automation_id=automation.id,
            ),
        )
    assert response.status_code == 404
