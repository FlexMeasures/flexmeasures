import pytest
from flask import url_for

from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor


def _unused_id_with_prefix(db, model, id_prefix: str) -> int:
    matching_id = int(f"{id_prefix}0")
    while db.session.get(model, matching_id) is not None:
        matching_id = int(f"{matching_id}0")
    return matching_id


def _unused_id_containing_but_not_starting_with(db, model, id_prefix: str) -> int:
    leading_digit = "9" if not id_prefix.startswith("9") else "8"
    decoy_id = int(f"{leading_digit}{id_prefix}")
    while db.session.get(model, decoy_id) is not None:
        decoy_id = int(f"{leading_digit}{decoy_id}")
    return decoy_id


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_get_assets_can_filter_by_asset_id_prefix(
    client,
    fresh_db,
    setup_api_fresh_test_data,
    requesting_user,
):
    asset = setup_api_fresh_test_data["some gas sensor"].generic_asset
    id_prefix = str(asset.id)
    matching_asset_id = _unused_id_with_prefix(fresh_db, GenericAsset, id_prefix)
    decoy_asset_id = _unused_id_containing_but_not_starting_with(
        fresh_db, GenericAsset, id_prefix
    )
    matching_asset = GenericAsset(
        id=matching_asset_id,
        name="matching asset ID prefix",
        generic_asset_type=asset.generic_asset_type,
        owner=asset.owner,
    )
    decoy_asset = GenericAsset(
        id=decoy_asset_id,
        name="decoy asset ID substring",
        generic_asset_type=asset.generic_asset_type,
        owner=asset.owner,
    )
    fresh_db.session.add_all([matching_asset, decoy_asset])
    fresh_db.session.flush()

    response = client.get(
        url_for("AssetAPI:index"),
        query_string={
            "account_id": asset.account_id,
            "filter": id_prefix,
        },
    )

    assert response.status_code == 200
    asset_ids = [a["id"] for a in response.json]
    assert set(asset_ids) == {asset.id, matching_asset.id}
    assert decoy_asset.id not in asset_ids
    assert all(str(asset_id).startswith(id_prefix) for asset_id in asset_ids)

    full_id_response = client.get(
        url_for("AssetAPI:index"),
        query_string={
            "account_id": asset.account_id,
            "filter": str(matching_asset.id),
        },
    )

    assert full_id_response.status_code == 200
    assert [a["id"] for a in full_id_response.json] == [matching_asset.id]


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_fetch_asset_sensors_can_filter_by_sensor_id_prefix(
    client,
    fresh_db,
    setup_api_fresh_test_data,
    requesting_user,
):
    sensor = setup_api_fresh_test_data["some gas sensor"]
    id_prefix = str(sensor.id)
    matching_sensor_id = _unused_id_with_prefix(fresh_db, Sensor, id_prefix)
    decoy_sensor_id = _unused_id_containing_but_not_starting_with(
        fresh_db, Sensor, id_prefix
    )
    matching_sensor = Sensor(
        name="matching sensor ID prefix",
        unit=sensor.unit,
        event_resolution=sensor.event_resolution,
        generic_asset=sensor.generic_asset,
    )
    matching_sensor.id = matching_sensor_id
    decoy_sensor = Sensor(
        name="decoy sensor ID substring",
        unit=sensor.unit,
        event_resolution=sensor.event_resolution,
        generic_asset=sensor.generic_asset,
    )
    decoy_sensor.id = decoy_sensor_id
    fresh_db.session.add_all([matching_sensor, decoy_sensor])
    fresh_db.session.flush()

    response = client.get(
        url_for("AssetAPI:asset_sensors", id=sensor.generic_asset_id),
        query_string={"filter": id_prefix},
    )

    assert response.status_code == 200
    assert response.json["num-records"] == 5
    assert response.json["filtered-records"] == 2
    sensor_ids = [s["id"] for s in response.json["data"]]
    assert set(sensor_ids) == {sensor.id, matching_sensor.id}
    assert decoy_sensor.id not in sensor_ids
    assert all(str(sensor_id).startswith(id_prefix) for sensor_id in sensor_ids)

    full_id_response = client.get(
        url_for("AssetAPI:asset_sensors", id=sensor.generic_asset_id),
        query_string={"filter": str(matching_sensor.id)},
    )

    assert full_id_response.status_code == 200
    assert full_id_response.json["filtered-records"] == 1
    assert [s["id"] for s in full_id_response.json["data"]] == [matching_sensor.id]
