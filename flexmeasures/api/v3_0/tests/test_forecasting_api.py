from datetime import timedelta

import pytest
from flask import url_for

from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor


@pytest.mark.parametrize(
    "regressor_field",
    ["future-regressors", "past-regressors", "regressors"],
)
@pytest.mark.parametrize("use_sensor_reference", [False, True])
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_trigger_forecast_with_unreadable_regressor_returns_403(
    app,
    setup_roles_users,
    setup_accounts,
    requesting_user,
    regressor_field,
    use_sensor_reference,
):
    """Triggering a forecast that uses a regressor the requesting user cannot read must return 403."""

    supplier_account = setup_accounts["Supplier"]
    prosumer_account = setup_accounts["Prosumer"]

    reference_suffix = "reference" if use_sensor_reference else "id"
    asset_type = GenericAssetType(
        name=f"test-asset-type-regressor-perm-{regressor_field}-{reference_suffix}"
    )
    db.session.add(asset_type)

    # Target sensor: owned by Supplier account – requesting user has create-children here
    supplier_asset = GenericAsset(
        name=f"supplier-target-asset-{regressor_field}-{reference_suffix}",
        generic_asset_type=asset_type,
        owner=supplier_account,
    )
    db.session.add(supplier_asset)
    target_sensor = Sensor(
        name=f"supplier-target-sensor-{regressor_field}-{reference_suffix}",
        unit="kW",
        event_resolution=timedelta(hours=1),
        generic_asset=supplier_asset,
    )
    db.session.add(target_sensor)

    # Regressor sensor: owned by Prosumer account – requesting user has no read access here
    prosumer_asset = GenericAsset(
        name=f"prosumer-private-regressor-asset-{regressor_field}-{reference_suffix}",
        generic_asset_type=asset_type,
        owner=prosumer_account,
    )
    db.session.add(prosumer_asset)
    private_regressor = Sensor(
        name=f"prosumer-private-regressor-sensor-{regressor_field}-{reference_suffix}",
        unit="kW",
        event_resolution=timedelta(hours=1),
        generic_asset=prosumer_asset,
    )
    db.session.add(private_regressor)
    db.session.commit()

    client = app.test_client()
    token = get_auth_token(client, "test_supplier_user_4@seita.nl", "testtest")

    payload = {
        "start": "2025-01-05T00:00:00+00:00",
        "end": "2025-01-05T02:00:00+00:00",
        "max-forecast-horizon": "PT1H",
        "forecast-frequency": "PT1H",
        "config": {
            "train-start": "2025-01-01T00:00:00+00:00",
            "retrain-frequency": "PT1H",
            regressor_field: [
                (
                    {
                        "sensor": private_regressor.id,
                        "source-types": ["forecaster"],
                    }
                    if use_sensor_reference
                    else private_regressor.id
                )
            ],
        },
    }

    trigger_url = url_for("SensorAPI:trigger_forecast", id=target_sensor.id)
    trigger_res = client.post(
        trigger_url, json=payload, headers={"Authorization": token}
    )
    assert trigger_res.status_code == 403
    assert trigger_res.json["status"] == "INVALID_SENDER"
    # Keep the config field path in the error so API users can fix the bad reference.
    assert (
        f"{{'json': {{'config': '{regressor_field}'}}}}" in trigger_res.json["message"]
    )
    # Do not leak metadata about a regressor sensor the caller cannot read.
    assert private_regressor.name not in trigger_res.json["message"]


@pytest.mark.parametrize("source_kind", ["account", "asset", "sensor"])
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_trigger_forecast_with_unreadable_annotation_regressor_returns_403(
    app,
    setup_roles_users,
    setup_accounts,
    requesting_user,
    source_kind,
):
    """Annotations used as a regressor must come from an account, asset or sensor the caller can read."""
    supplier_account = setup_accounts["Supplier"]
    prosumer_account = setup_accounts["Prosumer"]

    asset_type = GenericAssetType(name=f"test-asset-type-annotations-{source_kind}")
    db.session.add(asset_type)
    supplier_asset = GenericAsset(
        name=f"supplier-annotations-target-asset-{source_kind}",
        generic_asset_type=asset_type,
        owner=supplier_account,
    )
    target_sensor = Sensor(
        name=f"supplier-annotations-target-sensor-{source_kind}",
        unit="kW",
        event_resolution=timedelta(hours=1),
        generic_asset=supplier_asset,
    )
    prosumer_asset = GenericAsset(
        name=f"prosumer-annotated-asset-{source_kind}",
        generic_asset_type=asset_type,
        owner=prosumer_account,
    )
    prosumer_sensor = Sensor(
        name=f"prosumer-annotated-sensor-{source_kind}",
        unit="kW",
        event_resolution=timedelta(hours=1),
        generic_asset=prosumer_asset,
    )
    db.session.add_all([supplier_asset, target_sensor, prosumer_asset, prosumer_sensor])
    db.session.commit()
    source_id = {
        "account": prosumer_account.id,
        "asset": prosumer_asset.id,
        "sensor": prosumer_sensor.id,
    }[source_kind]

    client = app.test_client()
    token = get_auth_token(client, "test_supplier_user_4@seita.nl", "testtest")
    payload = {
        "start": "2025-01-05T00:00:00+00:00",
        "end": "2025-01-05T02:00:00+00:00",
        "max-forecast-horizon": "PT1H",
        "forecast-frequency": "PT1H",
        "config": {
            "train-start": "2025-01-01T00:00:00+00:00",
            "retrain-frequency": "PT1H",
            "annotation-regressors": [{source_kind: source_id}],
        },
    }
    trigger_res = client.post(
        url_for("SensorAPI:trigger_forecast", id=target_sensor.id),
        json=payload,
        headers={"Authorization": token},
    )
    assert trigger_res.status_code == 403, trigger_res.json
    assert f"{source_kind} {source_id}" in trigger_res.json["message"]

    # Annotations of the caller's own account are fine
    payload["config"]["annotation-regressors"] = [{"account": supplier_account.id}]
    trigger_res = client.post(
        url_for("SensorAPI:trigger_forecast", id=target_sensor.id),
        json=payload,
        headers={"Authorization": token},
    )
    assert trigger_res.status_code in (200, 202), trigger_res.json
