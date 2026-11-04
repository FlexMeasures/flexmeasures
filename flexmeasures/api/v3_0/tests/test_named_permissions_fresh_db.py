"""API regressions for resource deletion under the member role."""

import pytest
from flask import url_for

from flexmeasures import Sensor
from flexmeasures.data.models.generic_assets import GenericAsset


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_member_can_delete_empty_asset_but_not_asset_with_data(
    client, setup_api_fresh_test_data, requesting_user, fresh_db
):
    populated_asset = setup_api_fresh_test_data["some gas sensor"].generic_asset
    empty_asset = GenericAsset(
        name="empty member asset",
        generic_asset_type=populated_asset.generic_asset_type,
        owner=requesting_user.account,
    )
    fresh_db.session.add(empty_asset)
    fresh_db.session.flush()
    empty_id = empty_asset.id
    populated_id = populated_asset.id

    delete_empty = client.delete(url_for("AssetAPI:delete", id=empty_id))
    assert delete_empty.status_code == 204
    assert fresh_db.session.get(GenericAsset, empty_id) is None

    delete_populated = client.delete(url_for("AssetAPI:delete", id=populated_id))
    assert delete_populated.status_code == 403
    assert fresh_db.session.get(GenericAsset, populated_id) is not None
    assert (
        fresh_db.session.get(Sensor, setup_api_fresh_test_data["some gas sensor"].id)
        is not None
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_member_can_delete_empty_sensor_but_not_sensor_with_data(
    client, setup_api_fresh_test_data, requesting_user, fresh_db
):
    empty_sensor = setup_api_fresh_test_data["empty temperature sensor"]
    populated_sensor = setup_api_fresh_test_data["some gas sensor"]
    empty_id = empty_sensor.id
    populated_id = populated_sensor.id

    delete_empty = client.delete(url_for("SensorAPI:delete", id=empty_id))
    assert delete_empty.status_code == 204
    assert fresh_db.session.get(Sensor, empty_id) is None

    delete_populated = client.delete(url_for("SensorAPI:delete", id=populated_id))
    assert delete_populated.status_code == 403
    assert fresh_db.session.get(Sensor, populated_id) is not None
