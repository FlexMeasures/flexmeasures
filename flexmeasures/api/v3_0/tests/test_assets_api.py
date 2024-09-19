import json

from flask import url_for
import pytest
from sqlalchemy import select, func

from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.api.tests.utils import get_auth_token, UserContext, AccountContext
from flexmeasures.api.v3_0.tests.utils import get_asset_post_data


@pytest.mark.parametrize(
    "requesting_user, status_code",
    [
        (None, 401),  # the case without auth: authentication will fail
        (
            "test_dummy_user_3@seita.nl",
            403,
        ),  # fails authorization to get assets on another account
    ],
    indirect=["requesting_user"],
)
def test_get_assets_badauth(client, setup_api_test_data, requesting_user, status_code):
    """
    Attempt to get assets with wrong or missing auth.
    """
    test_prosumer = find_user_by_email("test_prosumer_user@seita.nl")
    query = {"account_id": test_prosumer.account.id}

    get_assets_response = client.get(url_for("AssetAPI:index"), query_string=query)
    print("Server responded with:\n%s" % get_assets_response.json)
    assert get_assets_response.status_code == status_code


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_get_asset_nonaccount_access(client, setup_api_test_data, requesting_user):
    """Without being on the same account, test correct responses when accessing one asset."""
    with UserContext("test_prosumer_user@seita.nl") as prosumer1:
        prosumer1_assets = prosumer1.account.generic_assets
    with UserContext("test_supplier_user_4@seita.nl") as supplieruser4:
        supplieruser4_assets = supplieruser4.account.generic_assets

    # okay to look at assets in own account
    asset_response = client.get(
        url_for("AssetAPI:fetch_one", id=supplieruser4_assets[0].id),
        follow_redirects=True,
    )
    assert asset_response.status_code == 200
    # not okay to see assets owned by other accounts
    asset_response = client.get(
        url_for("AssetAPI:fetch_one", id=prosumer1_assets[0].id),
        follow_redirects=True,
    )
    assert asset_response.status_code == 403
    # proper 404 for non-existing asset
    asset_response = client.get(
        url_for("AssetAPI:fetch_one", id=8171766575),
        follow_redirects=True,
    )
    assert asset_response.status_code == 404
    assert "not found" in asset_response.json["message"]


@pytest.mark.parametrize(
    "requesting_user, account_name, num_assets, use_pagination",
    [
        ("test_admin_user@seita.nl", "Prosumer", 1, False),
        ("test_admin_user@seita.nl", "Supplier", 2, False),
        ("test_consultant@seita.nl", "ConsultancyClient", 1, False),
        ("test_admin_user@seita.nl", "Prosumer", 1, True),
    ],
    indirect=["requesting_user"],
)
def test_get_assets(
    client,
    setup_api_test_data,
    setup_accounts,
    account_name,
    num_assets,
    use_pagination,
    requesting_user,
):
    """
    Get assets per account.
    Our user here is admin, so is allowed to see all assets.
    Pagination is tested only in passing, we should test filtering and page > 1
    """
    query = {"account_id": setup_accounts[account_name].id}
    if use_pagination:
        query["page"] = 1

    get_assets_response = client.get(
        url_for("AssetAPI:index"),
        query_string=query,
    )
    print("Server responded with:\n%s" % get_assets_response.json)
    assert get_assets_response.status_code == 200

    if use_pagination:
        assets = get_assets_response.json["data"]
        assert get_assets_response.json["num-records"] == num_assets
        assert get_assets_response.json["filtered-records"] == num_assets
    else:
        assets = get_assets_response.json

    assert len(assets) == num_assets

    if account_name == "Supplier":  # one deep dive
        turbine = {}
        for asset in assets:
            if asset["name"] == "Test wind turbine":
                turbine = asset
        assert turbine
        assert turbine["account_id"] == setup_accounts["Supplier"].id


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_get_asset_with_children(client, add_asset_with_children, requesting_user):
    """
    Get asset `parent` with children `child_1` and `child_2`.
    We expect the response to be the serialized asset including its
    child assets in the field `child_assets`.
    """

    parent = add_asset_with_children["parent"]
    get_assets_response = client.get(
        url_for("AssetAPI:fetch_one", id=parent.id),
    )
    print("Server responded with:\n%s" % get_assets_response.json)
    assert get_assets_response.status_code == 200
    assert len(get_assets_response.json["child_assets"]) == 2


@pytest.mark.parametrize("requesting_user", [None], indirect=True)
def test_get_public_assets_noauth(
    client, setup_api_test_data, setup_accounts, requesting_user
):
    get_assets_response = client.get(url_for("AssetAPI:public"))
    print("Server responded with:\n%s" % get_assets_response.json)
    assert get_assets_response.status_code == 401


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_get_public_assets(
    client, setup_api_test_data, setup_accounts, requesting_user
):
    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    get_assets_response = client.get(
        url_for("AssetAPI:public"), headers={"Authorization": auth_token}
    )
    print("Server responded with:\n%s" % get_assets_response.json)
    assert get_assets_response.status_code == 200
    assert len(get_assets_response.json) == 1
    assert get_assets_response.json[0]["name"] == "troposphere"


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_alter_an_asset(
    client, setup_api_test_data, setup_accounts, requesting_user, db
):
    # without being an account-admin, no asset can be created ...
    with AccountContext("Test Prosumer Account") as prosumer:
        prosumer_asset = prosumer.generic_assets[0]
    asset_creation_response = client.post(
        url_for("AssetAPI:post"),
        json={},
    )
    print(f"Creation Response: {asset_creation_response.json}")
    assert asset_creation_response.status_code == 403
    # ... or deleted ...
    asset_delete_response = client.delete(
        url_for("AssetAPI:delete", id=prosumer_asset.id),
        json={},
    )
    print(f"Deletion Response: {asset_delete_response.json}")
    assert asset_delete_response.status_code == 403
    # ... but editing is allowed.
    latitude, name = prosumer_asset.latitude, prosumer_asset.name
    asset_edit_response = client.patch(
        url_for("AssetAPI:patch", id=prosumer_asset.id),
        json={
            "latitude": 11.1,
            "name": "other",
        },
    )
    print(f"Editing Response: {asset_edit_response.json}")
    assert asset_edit_response.status_code == 200

    # Resetting changes to keep other tests clean here
    asset_edit_response = client.patch(
        url_for("AssetAPI:patch", id=prosumer_asset.id),
        json={
            "latitude": latitude,
            "name": name,
        },
    )
    print(f"Editing Response: {asset_edit_response.json}")
    assert asset_edit_response.status_code == 200

    audit_log_event = f"Updated asset '{prosumer_asset.name}': {prosumer_asset.id}; fields: Field: name, From: {name}, To: other"
    assert db.session.execute(
        select(AssetAuditLog).filter_by(
            event=audit_log_event,
            active_user_id=requesting_user.id,
            active_user_name=requesting_user.username,
            affected_asset_id=prosumer_asset.id,
        )
    ).scalar_one_or_none()

    audit_log_event = f"Updated asset '{prosumer_asset.name}': {prosumer_asset.id}; fields: Field: latitude, From: {latitude}, To: 11.1"
    assert db.session.execute(
        select(AssetAuditLog).filter_by(
            event=audit_log_event,
            active_user_id=requesting_user.id,
            active_user_name=requesting_user.username,
            affected_asset_id=prosumer_asset.id,
        )
    ).scalar_one_or_none()


@pytest.mark.parametrize(
    "bad_json_str, error_msg",
    [
        (None, "may not be null"),
        ("{", "Not a valid JSON"),
        ('{"hallo": world}', "Not a valid JSON"),
        ('{"sensors_to_show": [0, 1]}', "No sensor found"),  # no sensor with ID 0
        ('{"sensors_to_show": [1, [0, 2]]}', "No sensor found"),  # no sensor with ID 0
        (
            '{"sensors_to_show": [1, [2, [3, 4]]]}',
            "All elements in a list within 'sensors_to_show' must be integers.",
        ),  # nesting level max 1
        (
            '{"sensors_to_show": [1, "2"]}',
            "Invalid item type in 'sensors_to_show'. Expected int, list, or dict.",
        ),  # non-integer sensor ID
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_alter_an_asset_with_bad_json_attributes(
    client,
    setup_api_test_data,
    setup_accounts,
    bad_json_str,
    error_msg,
    requesting_user,
):
    """Check whether updating an asset's attributes with a badly structured JSON fails."""
    with AccountContext("Test Prosumer Account") as prosumer:
        prosumer_asset = prosumer.generic_assets[0]
    asset_edit_response = client.patch(
        url_for("AssetAPI:patch", id=prosumer_asset.id),
        json={"attributes": bad_json_str},
    )
    print(f"Editing Response: {asset_edit_response.json}")
    assert asset_edit_response.status_code == 422
    assert error_msg in asset_edit_response.json["message"]["json"]["attributes"][0]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_alter_an_asset_with_json_attributes(
    client, setup_api_test_data, setup_accounts, requesting_user
):
    """Check whether updating an asset's attributes with a properly structured JSON succeeds."""
    with AccountContext("Test Prosumer Account") as prosumer:
        prosumer_asset = prosumer.generic_assets[0]
        assert prosumer_asset.attributes[
            "sensors_to_show"
        ]  # make sure we run this test on an asset with a non-empty sensors_to_show attribute
    asset_edit_response = client.patch(
        url_for("AssetAPI:patch", id=prosumer_asset.id),
        json={
            "attributes": json.dumps(prosumer_asset.attributes)
        },  # we're not changing values to keep other tests clean here
    )
    print(f"Editing Response: {asset_edit_response.json}")
    assert asset_edit_response.status_code == 200


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_an_asset_with_other_account(client, setup_api_test_data, requesting_user):
    """Catch auth error, when account-admin posts an asset for another account"""
    with AccountContext("Test Supplier Account") as supplier:
        supplier_id = supplier.id
    post_data = get_asset_post_data()
    post_data["account_id"] = supplier_id
    asset_creation_response = client.post(
        url_for("AssetAPI:post"),
        json=post_data,
    )
    print(f"Creation Response: {asset_creation_response.json}")
    assert asset_creation_response.status_code == 422
    assert (
        "not allowed to create assets for this account"
        in asset_creation_response.json["message"]["json"]["account_id"][0]
    )


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_post_an_asset_with_nonexisting_field(
    client, setup_api_test_data, requesting_user
):
    """Posting a field that is unexpected leads to a 422"""
    post_data = get_asset_post_data()
    post_data["nnname"] = "This field does not exist"
    asset_creation = client.post(
        url_for("AssetAPI:post"),
        json=post_data,
    )
    assert asset_creation.status_code == 422
    assert asset_creation.json["message"]["json"]["nnname"][0] == "Unknown field."


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_posting_multiple_assets(client, setup_api_test_data, requesting_user):
    """We can only send one at a time"""
    post_data1 = get_asset_post_data()
    post_data2 = get_asset_post_data()
    post_data2["name"] = "Test battery 3"
    asset_creation = client.post(
        url_for("AssetAPI:post"),
        json=[post_data1, post_data2],
    )
    print(f"Response: {asset_creation.json}")
    assert asset_creation.status_code == 422
    assert asset_creation.json["message"]["json"]["_schema"][0] == "Invalid input type."


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_post_an_asset_with_invalid_data(
    client, setup_api_test_data, requesting_user, db
):
    """
    Add an asset with some fields having invalid data and one field missing.
    The right error messages should be in the response and the number of assets has not increased.
    """
    num_assets_before = len(requesting_user.account.generic_assets)

    post_data = get_asset_post_data()
    post_data["name"] = "Something new"
    post_data["longitude"] = 300.9
    del post_data["generic_asset_type_id"]

    post_asset_response = client.post(
        url_for("AssetAPI:post"),
        json=post_data,
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
        db.session.scalar(
            select(func.count())
            .select_from(GenericAsset)
            .filter_by(account_id=requesting_user.account.id)
        )
        == num_assets_before
    )


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_post_an_asset(client, setup_api_test_data, requesting_user, db):
    """
    Post one extra asset, as an admin user.
    TODO: Soon we'll allow creating assets on an account-basis, i.e. for users
          who have the user role "account-admin" or something similar. Then we'll
          test that here.
    """
    post_data = get_asset_post_data()
    post_assets_response = client.post(
        url_for("AssetAPI:post"),
        json=post_data,
    )
    print("Server responded with:\n%s" % post_assets_response.json)
    assert post_assets_response.status_code == 201
    assert post_assets_response.json["latitude"] == 30.1

    asset: GenericAsset = db.session.execute(
        select(GenericAsset).filter_by(name="Test battery 2")
    ).scalar_one_or_none()
    assert asset is not None
    assert asset.latitude == 30.1

    assert db.session.execute(
        select(AssetAuditLog).filter_by(
            affected_asset_id=asset.id,
            event=f"Created asset '{asset.name}': {asset.id}",
            active_user_id=requesting_user.id,
            active_user_name=requesting_user.username,
        )
    ).scalar_one_or_none()


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_delete_an_asset(client, setup_api_test_data, requesting_user, db):
    existing_asset = setup_api_test_data["some gas sensor"].generic_asset
    existing_asset_id, existing_asset_name = existing_asset.id, existing_asset.name

    delete_asset_response = client.delete(
        url_for("AssetAPI:delete", id=existing_asset_id),
    )
    assert delete_asset_response.status_code == 204
    deleted_asset = db.session.execute(
        select(GenericAsset).filter_by(id=existing_asset_id)
    ).scalar_one_or_none()
    assert deleted_asset is None

    audit_log = db.session.execute(
        select(AssetAuditLog).filter_by(
            event=f"Deleted asset '{existing_asset_name}': {existing_asset_id}",
            active_user_id=requesting_user.id,
            active_user_name=requesting_user.username,
        )
    ).scalar_one_or_none()
    assert audit_log.affected_asset_id is None


@pytest.mark.parametrize(
    "requesting_user",
    ["test_consultant@seita.nl"],
    indirect=True,
)
def test_consultant_can_read(
    client,
    setup_api_test_data,
    setup_accounts,
    requesting_user,
):
    """
    The Consultant Account reads the assets from the ConsultancyClient Account.
    """
    account_name = "ConsultancyClient"
    query = {"account_id": setup_accounts[account_name].id}

    get_assets_response = client.get(
        url_for("AssetAPI:index"),
        query_string=query,
    )
    print("Server responded with:\n%s" % get_assets_response.json)
    assert get_assets_response.status_code == 200
    assert len(get_assets_response.json) == 1
    assert get_assets_response.json[0]["name"] == "Test ConsultancyClient Asset"


@pytest.mark.parametrize("requesting_user", ["test_consultant@seita.nl"], indirect=True)
def test_consultant_can_not_patch(
    client, setup_api_test_data, setup_accounts, requesting_user, db
):
    """
    Try to edit an asset belonging to the ConsultancyClient account with the Consultant account.
    The Consultant account only has read access.
    """
    consultancy_client_asset = db.session.execute(
        select(GenericAsset).filter_by(name="Test ConsultancyClient Asset")
    ).scalar_one_or_none()
    print(consultancy_client_asset)

    asset_edit_response = client.patch(
        url_for("AssetAPI:patch", id=consultancy_client_asset.id),
        json={
            "latitude": 0,
        },
    )
    print(f"Editing Response: {asset_edit_response.json}")
    assert asset_edit_response.status_code == 403


@pytest.mark.parametrize(
    "requesting_user",
    ["test_consultancy_user_without_consultant_access@seita.nl"],
    indirect=True,
)
def test_consultancy_user_without_consultant_role(
    client,
    setup_api_test_data,
    setup_accounts,
    requesting_user,
):
    """
    The Consultant Account user without customer manager role can not read.
    """
    account_name = "ConsultancyClient"
    query = {"account_id": setup_accounts[account_name].id}

    get_assets_response = client.get(
        url_for("AssetAPI:index"),
        query_string=query,
    )
    print("Server responded with:\n%s" % get_assets_response.json)
    assert get_assets_response.status_code == 403


@pytest.mark.parametrize(
    "parent_name, child_name, fails",
    [
        ("parent", "child_4", False),
        (None, "child_1", False),
        (None, "child_1", True),
        ("parent", "child_1", True),
    ],
)
@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_post_an_asset_with_existing_name(
    client, add_asset_with_children, parent_name, child_name, fails, requesting_user, db
):
    """Catch DB error (Unique key violated) correctly.

    Cases:
        1) Create a child asset
        2) Create an orphan asset with a name that already exists under a parent asset
        3) Create an orphan asset with an existing name.
        4) Create a child asset with a name that already exists among its siblings.
    """

    post_data = get_asset_post_data()

    def get_asset_with_name(asset_name):
        return db.session.execute(
            select(GenericAsset).filter_by(name=asset_name)
        ).scalar_one_or_none()

    parent = get_asset_with_name(parent_name)

    post_data["name"] = child_name
    post_data["account_id"] = requesting_user.account_id

    if parent:
        post_data["parent_asset_id"] = parent.parent_asset_id

    asset_creation_response = client.post(
        url_for("AssetAPI:post"),
        json=post_data,
    )

    if fails:
        assert asset_creation_response.status_code == 422
        assert (
            "already exists"
            in asset_creation_response.json["message"]["json"]["name"][0]
        )
    else:
        assert asset_creation_response.status_code == 201

        for key, val in post_data.items():
            assert asset_creation_response.json[key] == val

        # check that the asset exists
        assert (
            db.session.get(GenericAsset, asset_creation_response.json["id"]) is not None
        )


@pytest.mark.parametrize(
    "requesting_user",
    ["test_consultant@seita.nl"],
    indirect=True,
)
def test_consultant_get_asset(
    client, setup_api_test_data, setup_accounts, requesting_user, db
):
    """
    The Consultant Account reads an asset from the ConsultancyClient Account.
    """
    asset = db.session.execute(
        select(GenericAsset).filter_by(name="Test ConsultancyClient Asset")
    ).scalar_one_or_none()

    get_asset_response = client.get(url_for("AssetAPI:get", id=asset.id))
    print("Server responded with:\n%s" % get_asset_response.json)
    assert get_asset_response.status_code == 200
    assert get_asset_response.json["name"] == "Test ConsultancyClient Asset"
