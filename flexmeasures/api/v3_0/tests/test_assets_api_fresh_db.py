from flask import url_for
import pytest
from sqlalchemy import select

from flexmeasures.api.tests.utils import AccountContext
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.api.v3_0.tests.utils import get_asset_post_data


@pytest.mark.parametrize(
    "requesting_user",
    [
        "test_admin_user@seita.nl",  # has the "site-admin" role
        "test_prosumer_user_2@seita.nl",  # has the "account-admin" role
    ],
    indirect=True,
)
def test_post_an_asset_as_admin(client, setup_api_fresh_test_data, requesting_user, db):
    """
    Post one extra asset, as an admin user.
    """
    with AccountContext("Test Prosumer Account") as prosumer:
        post_data = get_asset_post_data(
            account_id=prosumer.id,
            asset_type_id=prosumer.generic_assets[0].generic_asset_type.id,
        )
    if requesting_user.email == "test_prosumer_user_2@seita.nl":
        post_data["name"] = "Test battery 3"
    post_assets_response = client.post(
        url_for("AssetAPI:post"),
        json=post_data,
    )
    print("Server responded with:\n%s" % post_assets_response.json)
    assert post_assets_response.status_code == 201
    assert post_assets_response.json["latitude"] == 30.1

    asset: GenericAsset = db.session.execute(
        select(GenericAsset).filter_by(name=post_data["name"])
    ).scalar_one_or_none()
    assert asset is not None
    assert asset.latitude == 30.1


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_edit_an_asset(client, setup_api_fresh_test_data, requesting_user, db):
    with AccountContext("Test Supplier Account") as supplier:
        existing_asset = supplier.generic_assets[0]

    post_data = dict(latitude=10)
    edit_asset_response = client.patch(
        url_for("AssetAPI:patch", id=existing_asset.id),
        json=post_data,
    )
    assert edit_asset_response.status_code == 200
    updated_asset = db.session.execute(
        select(GenericAsset).filter_by(id=existing_asset.id)
    ).scalar_one_or_none()
    assert updated_asset.latitude == 10  # changed value
    assert updated_asset.longitude == existing_asset.longitude
    assert updated_asset.name == existing_asset.name


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_delete_an_asset(client, setup_api_fresh_test_data, requesting_user, db):
    with AccountContext("Test Prosumer Account") as prosumer:
        existing_asset_id = prosumer.generic_assets[0].id

    delete_asset_response = client.delete(
        url_for("AssetAPI:delete", id=existing_asset_id),
    )
    assert delete_asset_response.status_code == 204
    deleted_asset = db.session.execute(
        select(GenericAsset).filter_by(id=existing_asset_id)
    ).scalar_one_or_none()
    assert deleted_asset is None
