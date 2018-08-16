from flask import url_for

from bvp.data.services.users import find_user_by_email
from bvp.data.models.assets import Asset


def test_asset_crud_as_non_admin(client, as_prosumer):
    asset_index = client.get(url_for("AssetCrud:index"), follow_redirects=True)
    assert asset_index.status_code == 200
    prosumer = find_user_by_email("test_prosumer@seita.nl")
    prosumer2 = find_user_by_email("test_prosumer2@seita.nl")
    asset_page = client.get(url_for("AssetCrud:get", id="new"), follow_redirects=True)
    assert asset_page.status_code == 401
    asset_page = client.get(
        url_for("AssetCrud:get", id=prosumer.assets[0].id), follow_redirects=True
    )
    assert asset_page.status_code == 200
    asset_page = client.get(
        url_for("AssetCrud:get", id=prosumer2.assets[0].id), follow_redirects=True
    )
    assert asset_page.status_code == 401
    asset_page = client.get(
        url_for("AssetCrud:get", id=8171766575), follow_redirects=True
    )
    assert asset_page.status_code == 404
    asset_index = client.get(url_for("AssetCrud:owned_by", owner_id=prosumer2.id))
    assert asset_index.status_code == 401
    asset_index = client.get(url_for("AssetCrud:owned_by", owner_id=prosumer.id))
    assert asset_index.status_code == 200
    asset_creation = client.post(
        url_for("AssetCrud:post", id="create"), follow_redirects=True
    )
    assert asset_creation.status_code == 401


def test_new_asset_page(client, as_admin):
    asset_page = client.get(url_for("AssetCrud:get", id="new"), follow_redirects=True)
    assert asset_page.status_code == 200
    assert b"Creating a new asset" in asset_page.data


def test_asset_page(client, as_prosumer):
    prosumer = find_user_by_email("test_prosumer@seita.nl")
    asset_page = client.get(
        url_for("AssetCrud:get", id=prosumer.assets[0].id), follow_redirects=True
    )
    assert (
        "Editing asset %s" % prosumer.assets[0].display_name
    ).encode() in asset_page.data
    assert str(prosumer.assets[0].capacity_in_mw).encode() in asset_page.data
    assert str(prosumer.assets[0].latitude).encode() in asset_page.data
    assert str(prosumer.assets[0].longitude).encode() in asset_page.data


def test_assets_owned_by(client, as_admin):
    prosumer = find_user_by_email("test_prosumer@seita.nl")
    asset_index = client.get(url_for("AssetCrud:owned_by", owner_id=prosumer.id))
    for asset in prosumer.assets:
        assert asset.display_name.encode() in asset_index.data


def test_edit_asset(client, as_prosumer):
    prosumer = find_user_by_email("test_prosumer@seita.nl")
    existing_asset = prosumer.assets[1]
    asset_edit = client.post(
        url_for("AssetCrud:post", id=existing_asset.id),
        follow_redirects=True,
        data=dict(
            display_name=existing_asset.display_name,
            latitude=existing_asset.latitude,
            longitude=existing_asset.longitude,
            capacity_in_mw="33.33",
        ),
    )
    assert asset_edit.status_code == 200
    updated_asset = Asset.query.filter_by(id=existing_asset.id).one_or_none()
    assert updated_asset.display_name == existing_asset.display_name
    assert updated_asset.latitude == existing_asset.latitude
    assert updated_asset.longitude == existing_asset.longitude
    assert updated_asset.capacity_in_mw == 33.33


def test_add_asset(client, as_admin):
    prosumer2 = find_user_by_email("test_prosumer2@seita.nl")
    num_assets_before = len(prosumer2.assets)
    asset_creation = client.post(
        url_for("AssetCrud:post", id="create"),
        follow_redirects=True,
        data=dict(
            display_name="New Test Asset",
            asset_type_name="wind",
            owner=str(prosumer2.id),
            capacity_in_mw="100",
            latitude="70.4",
            longitude="30.9",
        ),
    )
    assert asset_creation.status_code == 200
    assert Asset.query.filter_by(owner_id=prosumer2.id).count() == num_assets_before + 1
    updated_asset = Asset.query.filter_by(latitude=70.4).one_or_none()
    assert updated_asset.display_name == "New Test Asset"
    assert updated_asset.capacity_in_mw == 100


def test_add_asset_with_new_owner(client, as_admin):
    new_user_email = "test_prosumer_new_owner@seita.nl"
    asset_creation = client.post(
        url_for("AssetCrud:post", id="create"),
        follow_redirects=True,
        data=dict(
            display_name="New Test Asset",
            asset_type_name="wind",
            owner="none chosen",
            new_owner_email=new_user_email,
            capacity_in_mw="100",
            latitude="70.4",
            longitude="30.9",
        ),
    )
    assert asset_creation.status_code == 200
    new_user = find_user_by_email(new_user_email)
    assert new_user
    assert Asset.query.filter_by(owner_id=new_user.id).count() == 1
    new_asset = Asset.query.filter_by(owner_id=new_user.id).one_or_none()
    assert new_asset.display_name == "New Test Asset"
    assert new_asset.capacity_in_mw == 100


def test_add_invalid_asset(client, as_admin):
    prosumer2 = find_user_by_email("test_prosumer2@seita.nl")
    num_assets_before = len(prosumer2.assets)
    asset_creation = client.post(
        url_for("AssetCrud:post", id="create"),
        follow_redirects=True,
        data=dict(
            display_name="New Test Asset",
            asset_type_name="wind",
            owner=str(prosumer2.id),
            capacity_in_mw="-100",
            latitude="70.4",
            longitude="300.9",
        ),
    )
    assert asset_creation.status_code == 200
    assert b"must be at least 0" in asset_creation.data
    assert b"must be between -180 and 180" in asset_creation.data
    assert Asset.query.filter_by(owner_id=prosumer2.id).count() == num_assets_before
