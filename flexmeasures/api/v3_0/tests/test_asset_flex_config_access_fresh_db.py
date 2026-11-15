"""Storing a flex-context or flex-model needs access to the sensors it refers to.

Scheduling later reads from these sensors and records results on the output ones, without checking them again,
so a stored reference to another account's sensor would let a member read from it or write into it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from flask import url_for
from sqlalchemy import select

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import Account


@pytest.fixture
def sensors_in_reach(fresh_db, setup_api_fresh_test_data):
    """A Prosumer asset to configure, and power and price sensors in the Prosumer account, the Supplier account and on a public asset."""
    db = fresh_db
    accounts = {
        name: db.session.execute(
            select(Account).filter_by(name=f"Test {name} Account")
        ).scalar_one()
        for name in ("Prosumer", "Supplier")
    }
    asset_type = db.session.execute(select(GenericAssetType)).scalars().first()
    assets = {
        "own": GenericAsset(
            name="site to configure",
            generic_asset_type=asset_type,
            owner=accounts["Prosumer"],
        ),
        "foreign": GenericAsset(
            name="other organisation's site",
            generic_asset_type=asset_type,
            owner=accounts["Supplier"],
        ),
        "public": GenericAsset(name="public market", generic_asset_type=asset_type),
    }
    sensors = {}
    for owner, asset in assets.items():
        for kind, unit in (("power", "kW"), ("price", "EUR/MWh")):
            sensors[f"{owner} {kind}"] = Sensor(
                name=f"{owner} {kind}",
                generic_asset=asset,
                unit=unit,
                event_resolution=timedelta(minutes=15),
            )
    db.session.add_all([*assets.values(), *sensors.values()])
    db.session.commit()
    return assets["own"].id, {name: sensor.id for name, sensor in sensors.items()}


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
@pytest.mark.parametrize(
    "field, config, expected_status",
    [
        # Inputs need read access.
        ("flex_context", {"consumption-price": {"sensor": "own price"}}, 200),
        ("flex_context", {"consumption-price": {"sensor": "public price"}}, 200),
        ("flex_context", {"consumption-price": {"sensor": "foreign price"}}, 403),
        ("flex_context", {"site-power-capacity": {"sensor": "foreign power"}}, 403),
        # Outputs need to be sensors the user may record data on.
        ("flex_context", {"aggregate-consumption": {"sensor": "own power"}}, 200),
        ("flex_context", {"aggregate-consumption": {"sensor": "foreign power"}}, 403),
        ("flex_context", {"aggregate-production": {"sensor": "public power"}}, 403),
        ("flex_context", {"aggregate-power": {"sensor": "own power"}}, 200),
        ("flex_context", {"aggregate-power": {"sensor": "public power"}}, 403),
        ("flex_model", {"consumption": {"sensor": "own power"}}, 200),
        ("flex_model", {"consumption": {"sensor": "foreign power"}}, 403),
        ("flex_model", {"production": {"sensor": "public power"}}, 403),
    ],
)
def test_patch_asset_flex_config_needs_access_to_its_sensors(
    client,
    fresh_db,
    sensors_in_reach,
    requesting_user,
    field,
    config,
    expected_status,
):
    asset_id, sensor_ids = sensors_in_reach
    ((config_key, reference),) = config.items()
    config = {config_key: {"sensor": sensor_ids[reference["sensor"]]}}

    response = client.patch(
        url_for("AssetAPI:patch", id=asset_id), json={field: config}
    )

    assert response.status_code == expected_status, response.json
    stored = getattr(fresh_db.session.get(GenericAsset, asset_id), field)
    if expected_status == 200:
        assert stored == config
    else:
        assert stored == {}


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_asset_flex_context_needs_access_to_its_sensors(
    client, fresh_db, sensors_in_reach, requesting_user
):
    """Creating an asset applies the same check as patching one."""
    asset_id, sensor_ids = sensors_in_reach
    own_asset = fresh_db.session.get(GenericAsset, asset_id)
    post_data = {
        "name": "new site",
        "account_id": own_asset.account_id,
        "generic_asset_type_id": own_asset.generic_asset_type_id,
        "latitude": 52.0,
        "longitude": 5.0,
        "flex_context": {
            "aggregate-consumption": {"sensor": sensor_ids["foreign power"]}
        },
    }
    response = client.post(url_for("AssetAPI:post"), json=post_data)
    assert response.status_code == 403, response.json
    assert (
        fresh_db.session.execute(
            select(GenericAsset).filter_by(name="new site")
        ).scalar_one_or_none()
        is None
    )

    post_data["flex_context"] = {
        "aggregate-consumption": {"sensor": sensor_ids["own power"]}
    }
    response = client.post(url_for("AssetAPI:post"), json=post_data)
    assert response.status_code == 201, response.json
