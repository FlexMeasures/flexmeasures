"""Plugin automations through authenticated API creation and job monitoring."""

from flask import url_for
import pytest

from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.user import User
from flexmeasures.data.services.automations import run_automation
from flexmeasures.data.tests.test_plugin_automations_fresh_db import (
    ingestion_assets as _ingestion_assets,
    ingestion_plugin as _ingestion_plugin,
    make_automation,
)

ingestion_assets = _ingestion_assets
ingestion_plugin = _ingestion_plugin


@pytest.fixture
def owned_ingestion_assets(fresh_db, ingestion_assets, setup_roles_users_fresh_db):
    root, sensors = ingestion_assets
    user = fresh_db.session.get(User, setup_roles_users_fresh_db["Test Prosumer User"])
    root.owner = user.account
    fresh_db.session.commit()
    return root, sensors


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_create_and_inspect_plugin_automation(
    fresh_db, app, ingestion_plugin, owned_ingestion_assets, requesting_user
):
    root, sensors = owned_ingestion_assets
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=root.id),
            json={
                "name": "Hourly meter ingestion",
                "type": "mock-ingestion",
                "cron": "0 * * * *",
                "config": {"sensor": sensors[0].id},
                "parameters": {"value": 7.0},
            },
        )
        assert response.status_code == 201, response.json
        automation_id = response.json["id"]
        automation = fresh_db.session.get(Automation, automation_id)
        assert automation.execution_user_id == requesting_user.id
        assert automation.generator.model == "MockIngestionGenerator"
        response = client.get(
            url_for("AssetAPI:get_automation", id=root.id, automation_id=automation_id)
        )
    assert response.status_code == 200, response.json
    assert response.json["type"] == "mock-ingestion"
    assert response.json["source"]["id"] == automation.generator_id
    assert response.json["parameters"] == {"value": 7.0}
    assert response.json["output-sensors"] == [
        {"id": sensors[0].id, "name": sensors[0].name}
    ]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
@pytest.mark.parametrize("invalid_field", ["config", "parameters"])
def test_plugin_api_rejects_unknown_configuration(
    fresh_db,
    app,
    ingestion_plugin,
    owned_ingestion_assets,
    requesting_user,
    invalid_field,
):
    root, sensors = owned_ingestion_assets
    message = {
        "name": "Invalid ingestion",
        "type": "mock-ingestion",
        "cron": "0 * * * *",
        "config": {"sensor": sensors[0].id},
        "parameters": {},
    }
    message[invalid_field]["unknown"] = 1
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=root.id), json=message
        )
    assert response.status_code == 422, response.json
    assert fresh_db.session.query(Automation).count() == 0


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_plugin_api_rejects_foreign_input(
    fresh_db, app, ingestion_plugin, owned_ingestion_assets, requesting_user
):
    root, sensors = owned_ingestion_assets
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=root.id),
            json={
                "name": "Foreign input ingestion",
                "type": "mock-ingestion",
                "cron": "0 * * * *",
                "config": {
                    "sensor": sensors[0].id,
                    "input-sensor": sensors[2].id,
                },
            },
        )
    assert response.status_code == 403, response.json
    assert fresh_db.session.query(Automation).count() == 0


@pytest.mark.parametrize(
    "requesting_user,expected_status",
    [("test_prosumer_user@seita.nl", 202), ("test_dummy_user_3@seita.nl", 403)],
    indirect=["requesting_user"],
)
def test_plugin_job_status_requires_asset_read_access(
    fresh_db,
    app,
    ingestion_plugin,
    owned_ingestion_assets,
    requesting_user,
    expected_status,
):
    root, sensors = owned_ingestion_assets
    automation = make_automation(fresh_db, root, sensors[0])
    result = run_automation(automation)
    with app.test_client() as client:
        response = client.get(url_for("JobAPI:get_job_status", uuid=result["job_id"]))
    assert response.status_code == expected_status, response.json
    if expected_status == 202:
        assert response.json["status"] == "QUEUED"
