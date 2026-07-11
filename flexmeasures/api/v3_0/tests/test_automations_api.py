"""Tests for the automations endpoints (GET /api/v3_0/assets/<id>/automations[/<automation_id>])."""

from __future__ import annotations

import pytest
from flask import url_for
from sqlalchemy import select

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
    assert day_ahead["recurrence_description"] == "At 06:00"
    assert day_ahead["active"] is True
    assert day_ahead["created_at"] is not None
    assert day_ahead["job_stats"] == {}  # this automation has not queued any jobs
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


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_nonexistent_automation(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.get(
            url_for("AssetAPI:get_automation", id=battery.id, automation_id=9999),
        )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        ("test_prosumer_user@seita.nl", 403),  # plain account member
        ("test_prosumer_user_2@seita.nl", 201),  # account admin
        ("test_dummy_user_3@seita.nl", 403),  # different account
    ],
    indirect=["requesting_user"],
)
def test_post_automation(
    app,
    db,
    add_battery_assets,
    requesting_user,
    expected_status_code,
):
    """Only account admins (and consultants) can create automations; parameters are validated by type."""
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Posted schedules",
                "cronstr": "0 0 * * *",
                "type": "schedules",
                "parameters": {"duration": "PT12H"},
            },
        )
    assert response.status_code == expected_status_code
    if expected_status_code == 201:
        assert response.json["name"] == "Posted schedules"
        assert response.json["active"] is True
        assert response.json["recurrence_description"] == "At 00:00"
        automation = db.session.get(Automation, response.json["id"])
        assert automation.parameters == {"duration": "PT12H"}
        # clean up for other tests in this module
        db.session.delete(automation)
        db.session.flush()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_automation_with_foreign_sensor(
    app,
    db,
    setup_accounts,
    add_battery_assets,
    requesting_user,
):
    """Referencing a sensor outside the caller's reach is forbidden."""
    from datetime import timedelta

    from flexmeasures.data.models.generic_assets import GenericAsset
    from flexmeasures.data.models.time_series import Sensor

    battery = add_battery_assets["Test battery"]
    foreign_asset = GenericAsset(
        name="Foreign asset",
        generic_asset_type=battery.generic_asset_type,
        owner=setup_accounts["Dummy"],
    )
    foreign_sensor = Sensor(
        "foreign power",
        generic_asset=foreign_asset,
        event_resolution=timedelta(minutes=15),
        unit="MW",
    )
    db.session.add(foreign_sensor)
    db.session.flush()
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Sneaky forecasts",
                "cronstr": "0 6 * * *",
                "type": "forecasts",
                "parameters": {"sensor": foreign_sensor.id},
            },
        )
    assert response.status_code == 403
    assert (
        db.session.execute(
            select(Automation).filter_by(name="Sneaky forecasts")
        ).scalar_one_or_none()
        is None
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_automation_with_invalid_parameters(
    app,
    add_battery_assets,
    requesting_user,
):
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Bad forecasts",
                "cronstr": "0 6 * * *",
                "type": "forecasts",
                "parameters": {},  # missing required sensor
            },
        )
    assert response.status_code == 422
    assert "sensor" in str(response.json)


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        ("test_prosumer_user@seita.nl", 403),  # plain account member
        ("test_prosumer_user_2@seita.nl", 200),  # account admin
    ],
    indirect=["requesting_user"],
)
def test_patch_automation(
    app,
    db,
    add_battery_assets,
    add_automations,
    requesting_user,
    expected_status_code,
):
    battery = add_battery_assets["Test battery"]
    automation = add_automations[0]
    original_name = automation.name
    with app.test_client() as client:
        response = client.patch(
            url_for(
                "AssetAPI:patch_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
            json={"name": "Renamed via API", "active": False},
        )
    assert response.status_code == expected_status_code
    if expected_status_code == 200:
        assert response.json["name"] == "Renamed via API"
        assert response.json["active"] is False
        # restore for other tests in this module
        automation.name = original_name
        automation.active = True
        db.session.flush()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_delete_automation(
    app,
    db,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    battery = add_battery_assets["Test battery"]
    automation = Automation(
        asset_id=battery.id,
        type="forecasts",
        name="To be deleted",
        cronstr="0 6 * * *",
        parameters={"sensor": battery.sensors[0].id},
    )
    db.session.add(automation)
    db.session.flush()
    with app.test_client() as client:
        response = client.delete(
            url_for(
                "AssetAPI:delete_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
        )
        assert response.status_code == 204
        assert db.session.get(Automation, automation.id) is None

        # deleting again yields the documented 404
        response = client.delete(
            url_for(
                "AssetAPI:delete_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
        )
        assert response.status_code == 404
