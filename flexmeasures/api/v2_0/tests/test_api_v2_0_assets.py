from flask import url_for
import pytest

from flexmeasures.data.models.assets import Asset
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.api.tests.utils import get_auth_token, UserContext
from flexmeasures.api.v2_0.tests.utils import get_asset_post_data


@pytest.mark.parametrize("use_auth", [False, True])
def test_get_assets_badauth(client, use_auth):
    """
    Attempt to get assets with wrong or missing auth.
    """
    # the case without auth: authentication will fail
    headers = {"content-type": "application/json"}
    query = {}
    if use_auth:
        # in this case, we successfully authenticate, but fail authorization
        headers["Authorization"] = get_auth_token(
            client, "test_supplier@seita.nl", "testtest"
        )
        test_prosumer_id = find_user_by_email("test_prosumer@seita.nl").id
        query = {"owner_id": test_prosumer_id}

    get_assets_response = client.get(
        url_for("flexmeasures_api_v2_0.get_assets"), query_string=query, headers=headers
    )
    print("Server responded with:\n%s" % get_assets_response.json)
    if use_auth:
        assert get_assets_response.status_code == 403
    else:
        assert get_assets_response.status_code == 401


def test_get_asset_nonadmin_access(client):
    """Without being an admin, test correct responses when accessing one asset."""
    with UserContext("test_prosumer@seita.nl") as prosumer:
        prosumer_assets = prosumer.assets
    with UserContext("test_supplier@seita.nl") as supplier:
        supplier_assets = supplier.assets
    headers = {
        "content-type": "application/json",
        "Authorization": get_auth_token(client, "test_supplier@seita.nl", "testtest"),
    }

    # okay to look at own asset
    asset_response = client.get(
        url_for("flexmeasures_api_v2_0.get_asset", id=supplier_assets[0].id),
        headers=headers,
        follow_redirects=True,
    )
    assert asset_response.status_code == 200
    # not okay to see assets owned by others
    asset_response = client.get(
        url_for("flexmeasures_api_v2_0.get_asset", id=prosumer_assets[0].id),
        headers=headers,
        follow_redirects=True,
    )
    assert asset_response.status_code == 403
    # proper 404 for non-existing asset
    asset_response = client.get(
        url_for("flexmeasures_api_v2_0.get_asset", id=8171766575),
        headers=headers,
        follow_redirects=True,
    )
    assert asset_response.status_code == 404
    assert "not found" in asset_response.json["message"]


@pytest.mark.parametrize("use_owner_id,num_assets", [(False, 7), (True, 1)])
def test_get_assets(client, use_owner_id, num_assets):
    """
    Get assets, either for all users (prosumer is admin, so is allowed to see all 7 assets) or for
    a unique one (supplier user has one asset ― "Test battery").
    """
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    test_supplier_id = find_user_by_email("test_supplier@seita.nl").id

    query = {}
    if use_owner_id:
        query["owner_id"] = test_supplier_id

    get_assets_response = client.get(
        url_for("flexmeasures_api_v2_0.get_assets"),
        query_string=query,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_assets_response.json)
    assert get_assets_response.status_code == 200
    assert len(get_assets_response.json) == num_assets

    battery = {}
    for asset in get_assets_response.json:
        if asset["name"] == "Test battery":
            battery = asset
    assert battery
    assert battery["soc_datetime"] == "2015-01-01T00:00:00+00:00"
    assert battery["owner_id"] == test_supplier_id
    assert battery["capacity_in_mw"] == 2


def test_alter_an_asset_wrongauth(client):
    # without admin and owner rights, no asset can be created ...
    with UserContext("test_prosumer@seita.nl") as prosumer:
        prosumer_asset = prosumer.assets[0]
    with UserContext("test_supplier@seita.nl") as supplier:
        auth_token = supplier.get_auth_token()
        supplier_asset = supplier.assets[0]
    asset_creation_response = client.post(
        url_for("flexmeasures_api_v2_0.post_assets"),
        headers={"content-type": "application/json", "Authorization": auth_token},
        json={},
    )
    print(f"Response: {asset_creation_response.json}")
    assert asset_creation_response.status_code == 403
    # ... or edited ...
    asset_edit_response = client.patch(
        url_for("flexmeasures_api_v2_0.patch_asset", id=prosumer_asset.id),
        headers={"content-type": "application/json", "Authorization": auth_token},
        json={},
    )
    assert asset_edit_response.status_code == 403
    # ... or deleted ...
    asset_delete_response = client.delete(
        url_for("flexmeasures_api_v2_0.delete_asset", id=prosumer_asset.id),
        headers={"content-type": "application/json", "Authorization": auth_token},
        json={},
    )
    assert asset_delete_response.status_code == 403
    # ... which is impossible even if you're the owner
    asset_delete_response = client.delete(
        url_for("flexmeasures_api_v2_0.delete_asset", id=supplier_asset.id),
        headers={"content-type": "application/json", "Authorization": auth_token},
        json={},
    )
    assert asset_delete_response.status_code == 403


def test_post_an_asset_with_existing_name(client):
    """Catch DB error (Unique key violated) correctly"""
    with UserContext("test_prosumer@seita.nl") as prosumer:
        auth_token = prosumer.get_auth_token()
        existing_asset = prosumer.assets[0]
    post_data = get_asset_post_data()
    post_data["name"] = existing_asset.name
    asset_creation = client.post(
        url_for("flexmeasures_api_v2_0.post_assets"),
        json=post_data,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    assert asset_creation.status_code == 422
    assert "already exists" in asset_creation.json["message"]["json"]["name"][0]


def test_post_an_asset_with_nonexisting_field(client):
    """Posting a field that is unexpected leads to a 422"""
    with UserContext("test_prosumer@seita.nl") as prosumer:
        auth_token = prosumer.get_auth_token()
    post_data = get_asset_post_data()
    post_data["nnname"] = "This field does not exist"
    asset_creation = client.post(
        url_for("flexmeasures_api_v2_0.post_assets"),
        json=post_data,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    assert asset_creation.status_code == 422
    assert asset_creation.json["message"]["json"]["nnname"][0] == "Unknown field."


def test_posting_multiple_assets(client):
    """We can only send one at a time"""
    with UserContext("test_prosumer@seita.nl") as prosumer:
        auth_token = prosumer.get_auth_token()
    post_data1 = get_asset_post_data()
    post_data2 = get_asset_post_data()
    post_data2["name"] = "Test battery 3"
    asset_creation = client.post(
        url_for("flexmeasures_api_v2_0.post_assets"),
        json=[post_data1, post_data2],
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print(f"Response: {asset_creation.json}")
    assert asset_creation.status_code == 422
    assert asset_creation.json["message"]["json"]["_schema"][0] == "Invalid input type."


def test_post_an_asset(client):
    """
    Post one extra asset, as the prosumer user (an admin).
    """
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    post_data = get_asset_post_data()
    post_assets_response = client.post(
        url_for("flexmeasures_api_v2_0.post_assets"),
        json=post_data,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_assets_response.json)
    assert post_assets_response.status_code == 201
    assert post_assets_response.json["latitude"] == 30.1

    asset: Asset = Asset.query.filter(Asset.name == "Test battery 2").one_or_none()
    assert asset is not None
    assert asset.capacity_in_mw == 3


def test_post_an_asset_with_invalid_data(client, db):
    """
    Add an asset with some fields having invalid data and one field missing.
    The right error messages should be in the response and the number of assets has not increased.
    """
    with UserContext("test_prosumer@seita.nl") as prosumer:
        num_assets_before = len(prosumer.assets)

    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")

    post_data = get_asset_post_data()
    post_data["latitude"] = 70.4
    post_data["longitude"] = 300.9
    post_data["capacity_in_mw"] = -100
    post_data["min_soc_in_mwh"] = 10
    post_data["max_soc_in_mwh"] = 5
    del post_data["unit"]

    post_asset_response = client.post(
        url_for("flexmeasures_api_v2_0.post_assets"),
        json=post_data,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_asset_response.json)
    assert post_asset_response.status_code == 422

    assert (
        "Must be greater than or equal to 0"
        in post_asset_response.json["message"]["json"]["capacity_in_mw"][0]
    )
    assert (
        "greater than or equal to -180 and less than or equal to 180"
        in post_asset_response.json["message"]["json"]["longitude"][0]
    )
    assert "required field" in post_asset_response.json["message"]["json"]["unit"][0]
    assert (
        "must be equal or higher than the minimum soc"
        in post_asset_response.json["message"]["json"]["max_soc_in_mwh"]
    )

    assert Asset.query.filter_by(owner_id=prosumer.id).count() == num_assets_before


def test_edit_an_asset(client, db):
    with UserContext("test_prosumer@seita.nl") as prosumer:
        existing_asset = prosumer.assets[1]

    post_data = dict(latitude=10, id=999)  # id will be ignored
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    edit_asset_response = client.patch(
        url_for("flexmeasures_api_v2_0.patch_asset", id=existing_asset.id),
        json=post_data,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    assert edit_asset_response.status_code == 200
    updated_asset = Asset.query.filter_by(id=existing_asset.id).one_or_none()
    assert updated_asset.latitude == 10  # changed value
    assert updated_asset.longitude == existing_asset.longitude
    assert updated_asset.capacity_in_mw == existing_asset.capacity_in_mw
    assert updated_asset.name == existing_asset.name


def test_delete_an_asset(client, db):
    with UserContext("test_prosumer@seita.nl") as prosumer:
        existing_asset_id = prosumer.assets[0].id

    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    delete_asset_response = client.delete(
        url_for("flexmeasures_api_v2_0.delete_asset", id=existing_asset_id),
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    assert delete_asset_response.status_code == 204
    deleted_asset = Asset.query.filter_by(id=existing_asset_id).one_or_none()
    assert deleted_asset is None
