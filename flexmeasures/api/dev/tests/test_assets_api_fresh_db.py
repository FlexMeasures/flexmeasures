from flask import url_for
import pytest

from flexmeasures.api.tests.utils import get_auth_token, AccountContext
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.api.dev.tests.utils import get_asset_post_data


@pytest.mark.parametrize("admin_kind", ["site-admin", "account-admin"])
def test_post_an_asset_as_admin(client, setup_api_fresh_test_data, admin_kind):
    """
    Post one extra asset, as an admin user.
    """
    post_data = get_asset_post_data()
    if admin_kind == "site-admin":
        auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    else:
        auth_token = get_auth_token(client, "test_prosumer_user_2@seita.nl", "testtest")
        post_data["name"] = "Test battery 3"
    post_assets_response = client.post(
        url_for("AssetAPI:post"),
        json=post_data,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_assets_response.json)
    assert post_assets_response.status_code == 201
    assert post_assets_response.json["latitude"] == 30.1

    asset: GenericAsset = GenericAsset.query.filter(
        GenericAsset.name == post_data["name"]
    ).one_or_none()
    assert asset is not None
    assert asset.latitude == 30.1


def test_edit_an_asset(client, setup_api_fresh_test_data):
    with AccountContext("Test Prosumer Account") as prosumer:
        existing_asset = prosumer.generic_assets[1]

    post_data = dict(latitude=10, id=999)  # id will be ignored
    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    edit_asset_response = client.patch(
        url_for("AssetAPI:patch", id=existing_asset.id),
        json=post_data,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    assert edit_asset_response.status_code == 200
    updated_asset = GenericAsset.query.filter_by(id=existing_asset.id).one_or_none()
    assert updated_asset.latitude == 10  # changed value
    assert updated_asset.longitude == existing_asset.longitude
    assert updated_asset.name == existing_asset.name


def test_delete_an_asset(client, setup_api_fresh_test_data):
    with AccountContext("Test Prosumer Account") as prosumer:
        existing_asset_id = prosumer.generic_assets[0].id

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    delete_asset_response = client.delete(
        url_for("AssetAPI:delete", id=existing_asset_id),
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    assert delete_asset_response.status_code == 204
    deleted_asset = GenericAsset.query.filter_by(id=existing_asset_id).one_or_none()
    assert deleted_asset is None
