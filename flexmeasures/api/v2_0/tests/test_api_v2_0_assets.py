from flask import url_for
import pytest

import pandas as pd

from flexmeasures.data.models.assets import Asset
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.api.tests.utils import check_deprecation, get_auth_token, UserContext
from flexmeasures.api.v2_0.tests.utils import get_asset_post_data


@pytest.mark.parametrize("use_owner_id, num_assets", [(False, 7), (True, 1)])
def test_get_assets(client, add_charging_station_assets, use_owner_id, num_assets):
    """
    Get assets, either for all users (our user here is admin, so is allowed to see all 7 assets) or for
    a unique one (prosumer user 2 has one asset ― "Test battery").
    """
    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    test_prosumer2_id = find_user_by_email("test_prosumer_user_2@seita.nl").id

    query = {}
    if use_owner_id:
        query["owner_id"] = test_prosumer2_id

    get_assets_response = client.get(
        url_for("flexmeasures_api_v2_0.get_assets"),
        query_string=query,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_assets_response.json)
    check_deprecation(get_assets_response)
    assert get_assets_response.status_code == 200
    assert len(get_assets_response.json) == num_assets

    battery = {}
    for asset in get_assets_response.json:
        if asset["name"] == "Test battery":
            battery = asset
    assert battery
    assert pd.Timestamp(battery["soc_datetime"]) == pd.Timestamp(
        "2015-01-01T00:00:00+01:00"
    )
    assert battery["owner_id"] == test_prosumer2_id
    assert battery["capacity_in_mw"] == 2


def test_post_an_asset(client):
    """
    Post one extra asset, as an admin user.
    TODO: Soon we'll allow creating assets on an account-basis, i.e. for users
          who have the user role "account-admin" or sthg similar. Then we'll
          test that here.
    """
    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    post_data = get_asset_post_data()
    post_assets_response = client.post(
        url_for("flexmeasures_api_v2_0.post_assets"),
        json=post_data,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_assets_response.json)
    check_deprecation(post_assets_response)
    assert post_assets_response.status_code == 201
    assert post_assets_response.json["latitude"] == 30.1

    asset: Asset = Asset.query.filter(Asset.name == "Test battery 2").one_or_none()
    assert asset is not None
    assert asset.capacity_in_mw == 3


def test_edit_an_asset(client, db):
    with UserContext("test_prosumer_user@seita.nl") as prosumer:
        existing_asset = prosumer.assets[1]

    post_data = dict(latitude=10, id=999)  # id will be ignored
    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    edit_asset_response = client.patch(
        url_for("flexmeasures_api_v2_0.patch_asset", id=existing_asset.id),
        json=post_data,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    check_deprecation(edit_asset_response)
    assert edit_asset_response.status_code == 200
    updated_asset = Asset.query.filter_by(id=existing_asset.id).one_or_none()
    assert updated_asset.latitude == 10  # changed value
    assert updated_asset.longitude == existing_asset.longitude
    assert updated_asset.capacity_in_mw == existing_asset.capacity_in_mw
    assert updated_asset.name == existing_asset.name


def test_delete_an_asset(client, db):
    with UserContext("test_prosumer_user@seita.nl") as prosumer:
        existing_asset_id = prosumer.assets[0].id

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    delete_asset_response = client.delete(
        url_for("flexmeasures_api_v2_0.delete_asset", id=existing_asset_id),
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    check_deprecation(delete_asset_response)
    assert delete_asset_response.status_code == 204
    deleted_asset = Asset.query.filter_by(id=existing_asset_id).one_or_none()
    assert deleted_asset is None
