from datetime import datetime

import pytest
from flask import url_for
from sqlalchemy import select

from flexmeasures.api.tests.utils import AccountContext
from flexmeasures.api.v3_0.tests.utils import get_asset_post_data
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor, TimedBelief

# The first 10-minute event of "some gas sensor", which both of its sources recorded as 91.3 (see add_incineration_line).
KPI_WINDOW = {
    "start": "2021-05-02T00:00:00+02:00",
    "end": "2021-05-02T00:10:00+02:00",
}


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


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_patch_asset_kpis_rejects_cross_account_sensor(
    client, setup_api_fresh_test_data, requesting_user, fresh_db
):
    """A member cannot save another organisation's sensor as a KPI."""
    victim_sensor = setup_api_fresh_test_data["some gas sensor"]
    with AccountContext("Test Prosumer Account") as account:
        own_asset_id = account.generic_assets[0].id

    response = client.patch(
        url_for("AssetAPI:patch", id=own_asset_id),
        json={
            "sensors_to_show_as_kpis": [
                {"title": "Gas", "sensor": victim_sensor.id, "function": "max"}
            ]
        },
    )

    assert (
        response.status_code == 403
    ), "Saving a KPI on a sensor of another organisation should be forbidden."
    assert (
        fresh_db.session.get(GenericAsset, own_asset_id).sensors_to_show_as_kpis == []
    ), "The refused KPI should not have been stored on the asset."


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_post_asset_kpis_rejects_cross_account_sensor(
    client, setup_api_fresh_test_data, requesting_user, fresh_db
):
    """A member cannot create an asset that shows another organisation's sensor as a KPI."""
    victim_sensor = setup_api_fresh_test_data["some gas sensor"]
    with AccountContext("Test Prosumer Account") as account:
        own_asset = account.generic_assets[0]
        own_asset_id, account_id, asset_type_id = (
            own_asset.id,
            account.id,
            own_asset.generic_asset_type_id,
        )

    def post_child_asset(name: str, kpis: list):
        data = get_asset_post_data(account_id=account_id, asset_type_id=asset_type_id)
        data.update(name=name, parent_asset_id=own_asset_id)
        data["sensors_to_show_as_kpis"] = kpis
        return client.post(url_for("AssetAPI:post"), json=data)

    response = post_child_asset(
        "child showing someone else's gas",
        [{"title": "Gas", "sensor": victim_sensor.id, "function": "max"}],
    )
    assert (
        response.status_code == 403
    ), "Creating an asset with a KPI on a sensor of another organisation should be forbidden."
    assert (
        fresh_db.session.scalar(
            select(GenericAsset).filter_by(name="child showing someone else's gas")
        )
        is None
    ), "The refused asset should not have been created."
    assert (
        post_child_asset("child showing no KPIs", []).status_code == 201
    ), "The same request without the KPI should be allowed, which shows it was the KPI that was refused."


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
@pytest.mark.parametrize(
    "kpis",
    [
        pytest.param(
            [{"title": "Gas", "sensor": 999999, "function": "max"}],
            id="nonexistent-sensor",
        ),
        pytest.param([{"title": "Gas", "sensor": "1"}], id="sensor-not-an-int"),
        pytest.param({"title": "Gas", "sensor": 1}, id="not-a-list"),
        pytest.param(
            [{"title": "Gas", "sensor": 1, "function": "median"}],
            id="unknown-function",
        ),
    ],
)
def test_post_asset_kpis_rejects_invalid_entries(
    client, setup_api_fresh_test_data, requesting_user, fresh_db, kpis
):
    """Invalid KPI input on asset creation gets a 422 naming the field, as it does on PATCH."""
    some_asset = fresh_db.session.scalars(select(GenericAsset)).first()
    data = get_asset_post_data(
        account_id=some_asset.account_id,
        asset_type_id=some_asset.generic_asset_type_id,
    )
    data["sensors_to_show_as_kpis"] = kpis

    response = client.post(url_for("AssetAPI:post"), json=data)

    assert (
        response.status_code == 422
    ), "Invalid KPI input should be refused as unprocessable, rather than crash the request."
    assert "sensors_to_show_as_kpis" in str(
        response.json["message"]
    ), "The error should name the field that holds the invalid input."


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_asset_kpis_omits_stored_cross_account_sensor(
    client, setup_api_fresh_test_data, requesting_user, fresh_db
):
    """A readable asset cannot expose data through an old KPI reference."""
    victim_sensor = setup_api_fresh_test_data["some gas sensor"]
    assert (
        fresh_db.session.scalar(
            select(TimedBelief.event_value).where(
                TimedBelief.sensor_id == victim_sensor.id,
                TimedBelief.event_start == datetime.fromisoformat(KPI_WINDOW["start"]),
            )
        )
        == 91.3
    ), "The other organisation's sensor should hold a value within the KPI window, so that an empty response below means it was left out, not that there was nothing to show."
    with AccountContext("Test Prosumer Account") as account:
        own_asset_id = account.generic_assets[0].id

    own_asset = fresh_db.session.get(GenericAsset, own_asset_id)
    own_asset.sensors_to_show_as_kpis = [
        {"title": "Gas", "sensor": victim_sensor.id, "function": "max"}
    ]
    fresh_db.session.commit()

    response = client.get(
        url_for("AssetAPI:get_kpis", id=own_asset_id), query_string=KPI_WINDOW
    )

    assert (
        response.status_code == 200
    ), "Reading the KPIs of one's own asset should be allowed."
    assert response.json == {
        "data": []
    }, "A stored KPI on a sensor of another organisation should be left out, rather than reveal that sensor's value."


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_get_asset_kpis_returns_readable_sensor(
    client, setup_api_fresh_test_data, requesting_user, fresh_db
):
    """An authorized KPI still returns its sensor's value."""
    sensor = setup_api_fresh_test_data["some gas sensor"]
    asset_id = sensor.generic_asset_id

    patch_response = client.patch(
        url_for("AssetAPI:patch", id=asset_id),
        json={
            "sensors_to_show_as_kpis": [
                {"title": "Gas", "sensor": sensor.id, "function": "max"}
            ]
        },
    )
    assert (
        patch_response.status_code == 200
    ), "Saving a KPI on a sensor of one's own organisation should be allowed."

    response = client.get(
        url_for("AssetAPI:get_kpis", id=asset_id), query_string=KPI_WINDOW
    )

    assert response.status_code == 200, "Reading the asset's KPIs should be allowed."
    assert (
        response.json["data"][0]["sensor"] == sensor.id
    ), "The KPI on a readable sensor should still be shown."
    assert (
        response.json["data"][0]["downsample_value"] == 91.3
    ), "The KPI should report the maximum within the KPI window, which holds only the sensor's first event, 91.3."
