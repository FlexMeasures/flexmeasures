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


@pytest.mark.parametrize(
    "model_params, status_codes",
    [
        # distributed training: the worker would listen on a port and connect to these hosts
        (
            {"machines": "127.0.0.1:12400,10.0.0.1:12400", "num_machines": 2},
            (422,),
        ),
        ({"num_threads": 64}, (422,)),
        ({"forcedsplits_filename": "/etc/passwd"}, (422,)),
        ({"n_estimators": 1_000_000}, (422,)),
        ({"max_depth": "6"}, (422,)),
        ({"max_depth": 6, "min_child_samples": 10}, (200, 202)),
        # each bound
        ({"max_depth": 9}, (422,)),
        ({"num_leaves": 65}, (422,)),
        ({"n_estimators": 301}, (422,)),
        # the combined limit: n_estimators × min(num_leaves, 2 ** max_depth) <= 8000
        ({"n_estimators": 300, "num_leaves": 64, "max_depth": 8}, (422,)),
        ({"n_estimators": 300, "max_depth": 8}, (422,)),  # 31 leaves by default
        ({"n_estimators": 250, "num_leaves": 32, "max_depth": 5}, (200, 202)),
        ({"n_estimators": 300, "num_leaves": 64}, (200, 202)),  # depth 3 by default
    ],
    ids=[
        "machines",
        "threads",
        "file",
        "huge",
        "string",
        "tuning",
        "deep",
        "leafy",
        "many-trees",
        "combined",
        "default-leaves",
        "at-the-limit",
        "default-depth",
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_trigger_forecast_accepts_only_bounded_model_params(
    app,
    setup_roles_users,
    setup_accounts,
    requesting_user,
    model_params,
    status_codes,
    request,
):
    """Model params from the API are limited to bounded tuning knobs."""
    case = request.node.callspec.id
    asset_type = GenericAssetType(name=f"test-asset-type-model-params-{case}")
    asset = GenericAsset(
        name=f"supplier-model-params-asset-{case}",
        generic_asset_type=asset_type,
        owner=setup_accounts["Supplier"],
    )
    sensor = Sensor(
        name="supplier-model-params-sensor",
        unit="kW",
        event_resolution=timedelta(hours=1),
        generic_asset=asset,
    )
    db.session.add_all([asset_type, asset, sensor])
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
            "model-params": model_params,
        },
    }
    trigger_res = client.post(
        url_for("SensorAPI:trigger_forecast", id=sensor.id),
        json=payload,
        headers={"Authorization": token},
    )
    assert trigger_res.status_code in status_codes, trigger_res.json
    if 422 in status_codes:
        assert "model-params" in str(trigger_res.json)
