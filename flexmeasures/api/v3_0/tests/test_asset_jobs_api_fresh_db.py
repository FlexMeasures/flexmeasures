import json
from datetime import timedelta

import pytest
from flask import url_for

from flexmeasures import Sensor
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset


@pytest.mark.parametrize(
    ("requesting_user", "can_read_automation"),
    (
        ("test_dummy_user_3@seita.nl", False),
        ("test_admin_user@seita.nl", True),
    ),
    indirect=["requesting_user"],
)
def test_asset_jobs_redact_inaccessible_automation_provenance(
    app,
    client,
    fresh_db,
    setup_accounts_fresh_db,
    setup_roles_users_fresh_db,
    setup_generic_assets_fresh_db,
    clean_redis,
    requesting_user,
    can_read_automation,
):
    source_asset = setup_generic_assets_fresh_db["test_battery"]
    target_asset = GenericAsset(
        name="Cross-organisation forecast target",
        generic_asset_type=source_asset.generic_asset_type,
        owner=setup_accounts_fresh_db["Dummy"],
    )
    target_sensor = Sensor(
        name="target sensor",
        generic_asset=target_asset,
        unit="MW",
        event_resolution=timedelta(minutes=15),
    )
    fresh_db.session.add_all([target_asset, target_sensor])
    fresh_db.session.flush()
    generator = DataSource(
        name="asset jobs automation generator",
        type="forecaster",
        model="TrainPredictPipeline",
    )
    automation = Automation(
        asset=source_asset,
        generator=generator,
        name="Confidential source automation",
        type="forecasting",
        cronstr="0 6 * * *",
        parameters={"sensor": target_sensor.id},
    )
    fresh_db.session.add(automation)
    fresh_db.session.flush()

    job = app.queues["forecasting"].enqueue(
        sum,
        [1, 2],
        meta={
            "sensor_id": target_sensor.id,
            "trigger": {
                "origin": "automation",
                "automation_id": automation.id,
            },
        },
    )
    app.job_cache.add(
        target_sensor.id,
        job.id,
        queue="forecasting",
        asset_or_sensor_type="sensor",
    )

    response = client.get(url_for("AssetAPI:get_jobs", id=target_asset.id))

    assert response.status_code == 200
    assert len(response.json["jobs"]) == 1
    job_data = response.json["jobs"][0]
    metadata = json.loads(job_data["metadata"])
    assert metadata["trigger"]["origin"] == "automation"
    if can_read_automation:
        assert (
            job_data["created_via"]
            == f"automation '{automation.name}' ({automation.id})"
        )
        assert metadata["trigger"]["automation_id"] == automation.id
    else:
        assert job_data["created_via"] == "automation"
        assert "automation_id" not in metadata["trigger"]
        assert automation.name not in response.text
