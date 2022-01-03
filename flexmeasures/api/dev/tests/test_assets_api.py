from flask import url_for
import pytest

from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.api.tests.utils import get_auth_token, UserContext, AccountContext
from flexmeasures.api.dev.tests.utils import get_asset_post_data


@pytest.mark.parametrize("use_auth", [False, True])
def test_get_assets_badauth(client, setup_api_test_data, use_auth):
    """
    Attempt to get assets with wrong or missing auth.
    """
    # the case without auth: authentication will fail
    headers = {"content-type": "application/json"}
    query = {}
    if use_auth:
        # in this case, we successfully authenticate, but fail authorization
        headers["Authorization"] = get_auth_token(
            client, "test_dummy_user_3@seita.nl", "testtest"
        )
        test_prosumer = find_user_by_email("test_prosumer_user@seita.nl")
        query = {"account_id": test_prosumer.account.id}

    get_assets_response = client.get(
        url_for("AssetAPI:index"), query_string=query, headers=headers
    )
    print("Server responded with:\n%s" % get_assets_response.json)
    if use_auth:
        assert get_assets_response.status_code == 403
    else:
        assert get_assets_response.status_code == 401


def test_get_asset_nonaccount_access(client, setup_api_test_data):
    """Without being on the same account, test correct responses when accessing one asset."""
    with UserContext("test_prosumer_user@seita.nl") as prosumer1:
        prosumer1_assets = prosumer1.account.generic_assets
    with UserContext("test_supplier_user_4@seita.nl") as supplieruser4:
        supplieruser4_assets = supplieruser4.account.generic_assets
    headers = {
        "content-type": "application/json",
        "Authorization": get_auth_token(
            client, "test_supplier_user_4@seita.nl", "testtest"
        ),
    }

    # okay to look at assets in own account
    asset_response = client.get(
        url_for("AssetAPI:fetch_one", id=supplieruser4_assets[0].id),
        headers=headers,
        follow_redirects=True,
    )
    assert asset_response.status_code == 200
    # not okay to see assets owned by other accounts
    asset_response = client.get(
        url_for("AssetAPI:fetch_one", id=prosumer1_assets[0].id),
        headers=headers,
        follow_redirects=True,
    )
    assert asset_response.status_code == 403
    # proper 404 for non-existing asset
    asset_response = client.get(
        url_for("AssetAPI:fetch_one", id=8171766575),
        headers=headers,
        follow_redirects=True,
    )
    assert asset_response.status_code == 404
    assert "not found" in asset_response.json["message"]


@pytest.mark.parametrize("account_name, num_assets", [("Prosumer", 2), ("Supplier", 1)])
def test_get_assets(
    client, setup_api_test_data, setup_accounts, account_name, num_assets
):
    """
    Get assets per account.
    Our user here is admin, so is allowed to see all assets.
    """
    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")

    query = {"account_id": setup_accounts[account_name].id}

    get_assets_response = client.get(
        url_for("AssetAPI:index"),
        query_string=query,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_assets_response.json)
    assert get_assets_response.status_code == 200
    assert len(get_assets_response.json) == num_assets

    if account_name == "Supplier":  # one deep dive
        turbine = {}
        for asset in get_assets_response.json:
            if asset["name"] == "Test wind turbine":
                turbine = asset
        assert turbine
        assert turbine["account_id"] == setup_accounts["Supplier"].id


def test_alter_an_asset(client, setup_api_test_data, setup_accounts):
    # without being an account-admin, no asset can be created ...
    with UserContext("test_prosumer_user@seita.nl") as prosumer1:
        auth_token = prosumer1.get_auth_token()  # not an account admin
    with AccountContext("Test Prosumer Account") as prosumer:
        prosumer_asset = prosumer.generic_assets[0]
    asset_creation_response = client.post(
        url_for("AssetAPI:post"),
        headers={"content-type": "application/json", "Authorization": auth_token},
        json={},
    )
    print(f"Creation Response: {asset_creation_response.json}")
    assert asset_creation_response.status_code == 403
    # ... or deleted ...
    asset_delete_response = client.delete(
        url_for("AssetAPI:delete", id=prosumer_asset.id),
        headers={"content-type": "application/json", "Authorization": auth_token},
        json={},
    )
    print(f"Deletion Response: {asset_delete_response.json}")
    assert asset_delete_response.status_code == 403
    # ... but editing is allowed.
    asset_edit_response = client.patch(
        url_for("AssetAPI:patch", id=prosumer_asset.id),
        headers={"content-type": "application/json", "Authorization": auth_token},
        json={
            "latitude": prosumer_asset.latitude
        },  # we're not changing values to keep other tests clean here
    )
    print(f"Editing Response: {asset_edit_response.json}")
    assert asset_edit_response.status_code == 200


def test_post_an_asset_with_existing_name(client, setup_api_test_data):
    """Catch DB error (Unique key violated) correctly"""
    with UserContext("test_admin_user@seita.nl") as admin_user:
        auth_token = admin_user.get_auth_token()
    with AccountContext("Test Prosumer Account") as prosumer:
        prosumer_id = prosumer.id
        existing_asset = prosumer.generic_assets[0]
    post_data = get_asset_post_data()
    post_data["name"] = existing_asset.name
    post_data["account_id"] = prosumer_id
    asset_creation_response = client.post(
        url_for("AssetAPI:post"),
        json=post_data,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print(f"Creation Response: {asset_creation_response.json}")
    assert asset_creation_response.status_code == 422
    assert (
        "already exists" in asset_creation_response.json["message"]["json"]["name"][0]
    )


def test_post_an_asset_with_nonexisting_field(client, setup_api_test_data):
    """Posting a field that is unexpected leads to a 422"""
    with UserContext("test_admin_user@seita.nl") as prosumer:
        auth_token = prosumer.get_auth_token()
    post_data = get_asset_post_data()
    post_data["nnname"] = "This field does not exist"
    asset_creation = client.post(
        url_for("AssetAPI:post"),
        json=post_data,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    assert asset_creation.status_code == 422
    assert asset_creation.json["message"]["json"]["nnname"][0] == "Unknown field."


def test_posting_multiple_assets(client, setup_api_test_data):
    """We can only send one at a time"""
    with UserContext("test_admin_user@seita.nl") as prosumer:
        auth_token = prosumer.get_auth_token()
    post_data1 = get_asset_post_data()
    post_data2 = get_asset_post_data()
    post_data2["name"] = "Test battery 3"
    asset_creation = client.post(
        url_for("AssetAPI:post"),
        json=[post_data1, post_data2],
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print(f"Response: {asset_creation.json}")
    assert asset_creation.status_code == 422
    assert asset_creation.json["message"]["json"]["_schema"][0] == "Invalid input type."


def test_post_an_asset_with_invalid_data(client, setup_api_test_data):
    """
    Add an asset with some fields having invalid data and one field missing.
    The right error messages should be in the response and the number of assets has not increased.
    """
    with UserContext("test_admin_user@seita.nl") as prosumer:
        num_assets_before = len(prosumer.assets)

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")

    post_data = get_asset_post_data()
    post_data["name"] = "Something new"
    post_data["longitude"] = 300.9
    del post_data["generic_asset_type_id"]

    post_asset_response = client.post(
        url_for("AssetAPI:post"),
        json=post_data,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % post_asset_response.json)
    assert post_asset_response.status_code == 422

    assert (
        "exceeds the maximum longitude"
        in post_asset_response.json["message"]["json"]["longitude"][0]
    )
    assert (
        "required field"
        in post_asset_response.json["message"]["json"]["generic_asset_type_id"][0]
    )

    assert (
        GenericAsset.query.filter_by(account_id=prosumer.id).count()
        == num_assets_before
    )
