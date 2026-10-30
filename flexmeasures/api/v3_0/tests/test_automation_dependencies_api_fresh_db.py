"""Naming the automations an automation waits for, through the API."""

from datetime import timedelta

import pytest
from flask import url_for

from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor


@pytest.fixture
def upstream_automations(
    fresh_db, setup_roles_users_fresh_db, setup_generic_assets_fresh_db
):
    """An automation on the prosumer's own battery, one on a public asset, and one on the supplier's wind turbine, all recurring at 06:00 UTC."""
    assets = setup_generic_assets_fresh_db
    battery = assets["test_battery"]
    sensor = Sensor(
        name="battery power",
        unit="MW",
        event_resolution=timedelta(minutes=15),
        generic_asset=battery,
    )
    generator = DataSource(
        name="forecaster", type="forecaster", model="TrainPredictPipeline"
    )
    fresh_db.session.add_all([sensor, generator])
    fresh_db.session.flush()
    automations = {
        key: Automation(
            asset=assets[asset_key],
            generator=generator,
            type="forecasting",
            name=f"Upstream on {asset_key}",
            cronstr="0 6 * * *",
            timezone="UTC",
            parameters={},
        )
        for key, asset_key in (
            ("own", "test_battery"),
            ("public", "troposphere"),
            ("foreign", "test_wind_turbine"),
        )
    }
    fresh_db.session.add_all(automations.values())
    fresh_db.session.commit()
    return battery, sensor, automations


def _post(client, battery, sensor, depends_on, cron="0 6 * * *"):
    return client.post(
        url_for("AssetAPI:post_automation", id=battery.id),
        json={
            "name": "Downstream forecasts",
            "cron": cron,
            "timezone": "UTC",
            "type": "forecasting",
            "parameters": {"sensor": sensor.id},
            "depends-on": depends_on,
        },
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_post_automation_waiting_for_readable_automations(
    app, fresh_db, upstream_automations, requesting_user
):
    """Upstream automations can be on the user's own assets and on public ones, and the response names them."""
    battery, sensor, upstream = upstream_automations
    with app.test_client() as client:
        response = _post(
            client,
            battery,
            sensor,
            [
                {"automation": upstream["own"].id},
                {"automation": upstream["public"].id, "allow-failure": True},
            ],
        )
        assert response.status_code == 201, response.json
        assert response.json["depends-on"] == [
            {"automation": upstream["own"].id, "allow-failure": False},
            {"automation": upstream["public"].id, "allow-failure": True},
        ]
        listing = client.get(url_for("AssetAPI:get_automations", id=battery.id))
    listed = {
        automation["id"]: automation for automation in listing.json["automations"]
    }
    assert listed[response.json["id"]]["depends-on"] == response.json["depends-on"]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_post_automation_refuses_to_wait_for_an_unreadable_automation(
    app, fresh_db, upstream_automations, requesting_user
):
    battery, sensor, upstream = upstream_automations
    with app.test_client() as client:
        response = _post(
            client, battery, sensor, [{"automation": upstream["foreign"].id}]
        )
    assert response.status_code == 403, response.json
    assert (
        fresh_db.session.query(Automation)
        .filter_by(name="Downstream forecasts")
        .count()
        == 0
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_post_automation_waiting_for_one_on_another_schedule(
    app, fresh_db, upstream_automations, requesting_user
):
    """A run waits for the latest upstream run due at or before its own time, so the schedules need not match."""
    battery, sensor, upstream = upstream_automations
    with app.test_client() as client:
        response = _post(
            client,
            battery,
            sensor,
            [{"automation": upstream["own"].id}],
            cron="0 7 * * *",
        )
    assert response.status_code == 201, response.json
    assert response.json["depends-on"] == [
        {"automation": upstream["own"].id, "allow-failure": False}
    ]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_patch_automation_dependencies(
    app, fresh_db, upstream_automations, requesting_user
):
    """Dependencies can be replaced and cleared, and the schedule can change while they stay."""
    battery, sensor, upstream = upstream_automations
    with app.test_client() as client:
        created = _post(client, battery, sensor, [{"automation": upstream["own"].id}])
        assert created.status_code == 201, created.json
        url = url_for(
            "AssetAPI:patch_automation", id=battery.id, automation_id=created.json["id"]
        )

        moved = client.patch(url, json={"cron": "0 7 * * *"})
        assert moved.status_code == 200, moved.json
        assert moved.json["depends-on"] == [
            {"automation": upstream["own"].id, "allow-failure": False}
        ]

        replaced = client.patch(
            url,
            json={
                "depends-on": [
                    {"automation": upstream["public"].id, "allow-failure": True}
                ]
            },
        )
        assert replaced.status_code == 200, replaced.json
        assert replaced.json["depends-on"] == [
            {"automation": upstream["public"].id, "allow-failure": True}
        ]

        cleared = client.patch(url, json={"depends-on": []})
    assert cleared.status_code == 200, cleared.json
    assert cleared.json["depends-on"] == []
    assert cleared.json["cron"] == "0 7 * * *"


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_patch_automation_refuses_to_wait_for_an_unreadable_automation(
    app, fresh_db, upstream_automations, requesting_user
):
    battery, sensor, upstream = upstream_automations
    with app.test_client() as client:
        response = client.patch(
            url_for(
                "AssetAPI:patch_automation",
                id=battery.id,
                automation_id=upstream["own"].id,
            ),
            json={"depends-on": [{"automation": upstream["foreign"].id}]},
        )
    assert response.status_code == 403, response.json
    fresh_db.session.expire_all()
    assert fresh_db.session.get(Automation, upstream["own"].id).dependencies == []
