import json
from datetime import timedelta

from flask import url_for
import pytest
from sqlalchemy import select, func

from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.api.tests.utils import get_auth_token, UserContext, AccountContext
from flexmeasures.api.v3_0.tests.utils import get_asset_post_data, check_audit_log_event
from flexmeasures.api.common.utils.api_utils import copy_asset
from flexmeasures.utils.unit_utils import is_valid_unit


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_asset_types(
    client, setup_api_test_data, setup_roles_users, requesting_user
):
    get_asset_types_response = client.get(url_for("AssetTypesAPI:index"))
    print("Server responded with:\n%s" % get_asset_types_response.json)
    assert get_asset_types_response.status_code == 200
    assert isinstance(get_asset_types_response.json, list)
    assert len(get_asset_types_response.json) > 0
    assert isinstance(get_asset_types_response.json[0], dict)
    for key in ("id", "name", "description"):
        assert key in get_asset_types_response.json[0].keys()


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
    ("whose_asset", "exp_status"),
    [
        # okay to look at assets in own account
        ("test_supplier_user_4@seita.nl", 200),
        # not okay to see assets owned by other accounts
        ("test_prosumer_user@seita.nl", 403),
        # proper 404 for non-existing asset
        (None, 404),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_get_asset_nonaccount_access(
    client, setup_api_test_data, whose_asset, exp_status, requesting_user
):
    """Without being on the same account, test correct responses when accessing one asset."""
    if isinstance(whose_asset, str):
        with UserContext(whose_asset) as owner:
            asset_id = owner.account.generic_assets[0].id
    else:
        asset_id = 8171766575  # non-existent asset ID

    asset_response = client.get(
        url_for("AssetAPI:fetch_one", id=asset_id),
        follow_redirects=True,
    )
    assert asset_response.status_code == exp_status
    if exp_status == 404:
        assert asset_response.json["message"] == "No asset found with ID 8171766575."


@pytest.mark.parametrize(
    "requesting_user, account_name, num_assets, use_pagination, sort_by, sort_dir, expected_name_of_first_asset",
    [
        ("test_admin_user@seita.nl", "Prosumer", 1, False, None, None, None),
        ("test_admin_user@seita.nl", "Supplier", 2, False, None, None, None),
        (
            "test_admin_user@seita.nl",
            "Supplier",
            2,
            False,
            "name",
            "asc",
            "incineration line",
        ),
        (
            "test_admin_user@seita.nl",
            "Supplier",
            2,
            False,
            "name",
            "desc",
            "Test wind turbine",
        ),
        ("test_consultant@seita.nl", "ConsultancyClient", 1, False, None, None, None),
        ("test_admin_user@seita.nl", "Prosumer", 1, True, None, None, None),
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
    sort_by,
    sort_dir,
    expected_name_of_first_asset,
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

    if sort_by:
        query["sort_by"] = sort_by

    if sort_dir:
        query["sort_dir"] = sort_dir

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

        if sort_by:
            assert assets[0]["name"] == expected_name_of_first_asset

    assert len(assets) == num_assets

    if account_name == "Supplier":  # one deep dive
        turbine = {}
        for asset in assets:
            if asset["name"] == "Test wind turbine":
                turbine = asset
        assert turbine
        assert turbine["account_id"] == setup_accounts["Supplier"].id


@pytest.mark.parametrize(
    "requesting_user, sort_by, sort_dir, expected_name_of_first_sensor",
    [
        ("test_admin_user@seita.nl", None, None, None),
        ("test_admin_user@seita.nl", "name", "asc", "empty temperature sensor"),
        ("test_admin_user@seita.nl", "name", "desc", "some temperature sensor"),
    ],
    indirect=["requesting_user"],
)
def test_fetch_asset_sensors(
    client,
    setup_api_test_data,
    requesting_user,
    sort_by,
    sort_dir,
    expected_name_of_first_sensor,
):
    """
    Retrieve all sensors associated with a specific asset.

    This test checks for these metadata fields and the number of sensors returned, as well as
    confirming that the response is a list of dictionaries, each containing a valid unit.
    """

    query = {}

    if sort_by:
        query["sort_by"] = sort_by

    if sort_dir:
        query["sort_dir"] = sort_dir

    asset_id = setup_api_test_data["some gas sensor"].generic_asset_id
    response = client.get(
        url_for("AssetAPI:asset_sensors", id=asset_id), query_string=query
    )

    print("Server responded with:\n%s" % response.json)

    assert response.status_code == 200
    assert response.json["status"] == 200
    assert isinstance(response.json["data"], list)
    assert isinstance(response.json["data"][0], dict)
    assert is_valid_unit(response.json["data"][0]["unit"])
    assert response.json["num-records"] == 3
    assert response.json["filtered-records"] == 3

    if sort_by:
        assert response.json["data"][0]["name"] == expected_name_of_first_sensor


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

    check_audit_log_event(
        db=db,
        event=f"Updated: name, From: {name}, To: other",
        user=requesting_user,
        asset=prosumer_asset,
    )
    check_audit_log_event(
        db=db,
        event=f"Updated: latitude, From: {latitude}, To: 11.1",
        user=requesting_user,
        asset=prosumer_asset,
    )


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

    check_audit_log_event(
        db=db,
        event=f"Created asset '{asset.name}': {asset.id}",
        user=requesting_user,
        asset=asset,
    )


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
def test_consultant_can_patch(
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
    assert asset_edit_response.status_code == 200


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

    def get_asset_by_name(asset_name):
        return db.session.execute(
            select(GenericAsset).filter_by(name=asset_name)
        ).scalar_one_or_none()

    parent = None
    if parent_name:
        parent = get_asset_by_name(parent_name)

    post_data["name"] = child_name
    post_data["account_id"] = requesting_user.account_id

    if parent:
        post_data["parent_asset_id"] = parent.parent_asset_id
    else:
        post_data["parent_asset_id"] = None

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


def test_copy_asset(setup_api_test_data, setup_accounts, db):
    """
    Test all four placement use cases for copy_asset and verify direct sensors are copied.

    1. Neither account nor parent given  → same account, same parent (sibling copy).
    2. Only account given                → top-level asset in the given account.
    3. Only parent given                 → under the parent, inheriting its account.
    4. Both account and parent given     → under the parent, in the given account
                                           (cross-account parent relationship allowed).
    """
    prosumer_account = setup_accounts["Prosumer"]
    supplier_account = setup_accounts["Supplier"]

    # Source assets created by setup_generic_assets (via setup_api_test_data dependency)
    battery = db.session.scalars(
        select(GenericAsset).filter_by(
            account_id=prosumer_account.id,
            name="Test grid connected battery storage",
        )
    ).first()
    turbine = db.session.scalars(
        select(GenericAsset).filter_by(name="Test wind turbine")
    ).first()

    assert battery is not None, "Battery asset must exist in Prosumer account"
    assert turbine is not None, "Wind turbine asset must exist in Supplier account"

    # Add a deterministic sensor on battery so we can verify deep copy behavior.
    source_sensor = Sensor(
        name="copy-source-sensor",
        generic_asset=battery,
        event_resolution=timedelta(minutes=15),
        unit="kW",
    )
    db.session.add(source_sensor)
    db.session.flush()

    # Create a parent asset in the Supplier account for use cases 3 and 4.
    parent = GenericAsset(
        name="Test parent for copy",
        generic_asset_type=battery.generic_asset_type,
        owner=supplier_account,
    )
    db.session.add(parent)
    db.session.flush()

    # 1. Neither given → sibling copy (same account, same parent)
    copy1 = copy_asset(battery)
    assert copy1.name == f"{battery.name} (Copy)"
    assert copy1.account_id == battery.account_id
    assert copy1.parent_asset_id == battery.parent_asset_id  # None

    copied_sensor = db.session.scalars(
        select(Sensor).filter(
            Sensor.generic_asset_id == copy1.id,
            Sensor.name == source_sensor.name,
        )
    ).first()
    assert copied_sensor is not None
    assert copied_sensor.unit == source_sensor.unit
    assert copied_sensor.event_resolution == source_sensor.event_resolution

    # 2. Only account given → top-level in target account
    # Use the turbine so the name doesn't clash with copy1 (parent_asset_id is None for both).
    copy2 = copy_asset(turbine, account=prosumer_account)
    assert copy2.name == f"{turbine.name} (Copy)"
    assert copy2.account_id == prosumer_account.id
    assert copy2.parent_asset_id is None

    # 3. Only parent given → under parent, inherits parent's account
    copy3 = copy_asset(battery, parent_asset=parent)
    assert copy3.name == f"{battery.name} (Copy)"
    assert copy3.account_id == parent.account_id  # Supplier account
    assert copy3.parent_asset_id == parent.id

    # 4. Both given → under parent, in explicitly given account (cross-account)
    copy4 = copy_asset(turbine, account=prosumer_account, parent_asset=parent)
    assert copy4.name == f"{turbine.name} (Copy)"
    assert copy4.account_id == prosumer_account.id
    assert copy4.parent_asset_id == parent.id


def test_copy_asset_increments_name_under_same_parent(
    setup_api_test_data, setup_accounts, db
):
    """
    Copying the same asset repeatedly under the same parent increments copy names.

    Expected pattern:
    - first copy  -> ``<name> (Copy)``
    - second copy -> ``<name> (Copy 2)``
    - third copy  -> ``<name> (Copy 3)``
    """
    prosumer_account = setup_accounts["Prosumer"]
    battery = db.session.scalars(
        select(GenericAsset).filter_by(
            account_id=prosumer_account.id,
            name="Test grid connected battery storage",
        )
    ).first()
    assert battery is not None

    # Create a dedicated parent so this test is independent of others.
    parent = GenericAsset(
        name="Test parent for duplicate-name failure",
        generic_asset_type_id=battery.generic_asset_type_id,
        account_id=prosumer_account.id,
    )
    db.session.add(parent)
    db.session.flush()

    # First copy under the parent.
    first_copy = copy_asset(battery, parent_asset=parent)
    assert first_copy.parent_asset_id == parent.id
    assert first_copy.name == f"{battery.name} (Copy)"

    # Second and third copies increment the suffix.
    second_copy = copy_asset(battery, parent_asset=parent)
    assert second_copy.parent_asset_id == parent.id
    assert second_copy.name == f"{battery.name} (Copy 2)"

    third_copy = copy_asset(battery, parent_asset=parent)
    assert third_copy.parent_asset_id == parent.id
    assert third_copy.name == f"{battery.name} (Copy 3)"


def test_copy_asset_to_another_account_preserves_config(
    setup_api_test_data, setup_accounts, setup_markets, setup_generic_asset_types, db
):
    """
    Copy a richly configured asset from one account to another and verify everything
    is preserved correctly.

    Source asset layout (Prosumer account):

    House  (EMS)
    ├── flex_context:
    │     - consumption-price  → sensor on the public epex asset (no account)
    │     - site-power-capacity → sensor on the House itself (kW capacity)
    ├── EV charger 1  (child)
    │     - flex_model: { "power-capacity": "7.4 kW", "soc-unit": "kWh" }
    │     - sensors: power (kW), energy (kWh)
    └── EV charger 2  (child)
          - flex_model: { "power-capacity": "7.4 kW", "soc-unit": "kWh" }
          - sensors: power (kW), energy (kWh)

    Assertions after copying House to the Supplier account:
    1. The copy lands in the Supplier account with the expected name.
    2. The copy is a top-level asset (no parent).
    3. flex_context is preserved verbatim (sensor IDs are unchanged).
    4. copy_asset performs a deep subtree copy: child assets are duplicated.
    5. Sensors on copied child assets are duplicated.
    """
    prosumer_account = setup_accounts["Prosumer"]
    supplier_account = setup_accounts["Supplier"]

    # The epex_da sensor lives on the public "epex" asset (account_id=None).
    price_sensor = setup_markets["epex_da"]
    assert price_sensor.generic_asset.account_id is None, "epex must be a public asset"

    asset_type = setup_generic_asset_types["battery"]
    charger_type = setup_generic_asset_types["wind"]

    # Build the source house asset.
    # Use integer IDs (not ORM object references) to avoid SQLAlchemy cascade
    # issues with potentially-detached session objects from earlier tests.
    house = GenericAsset(
        name="Test house for rich copy",
        generic_asset_type_id=asset_type.id,
        account_id=prosumer_account.id,
    )
    db.session.add(house)
    db.session.flush()  # obtain house.id before adding sensors

    # A kW sensor on the house itself, referenced as the site-power-capacity.
    site_capacity_sensor = Sensor(
        name="site capacity",
        generic_asset=house,
        event_resolution=timedelta(minutes=15),
        unit="kW",
    )
    db.session.add(site_capacity_sensor)
    db.session.flush()

    house.flex_context = {
        "consumption-price": {"sensor": price_sensor.id},
        "site-power-capacity": {"sensor": site_capacity_sensor.id},
    }

    # Two child assets, each with two sensors and a two-setting flex_model.
    for i in range(1, 3):
        charger = GenericAsset(
            name=f"EV charger {i}",
            generic_asset_type_id=charger_type.id,
            account_id=prosumer_account.id,
            parent_asset_id=house.id,
            flex_model={"power-capacity": "7.4 kW", "soc-unit": "kWh"},
        )
        db.session.add(charger)
        db.session.flush()
        for j, unit in enumerate(["kW", "kWh"], start=1):
            db.session.add(
                Sensor(
                    name=f"charger {i} sensor {j}",
                    generic_asset=charger,
                    event_resolution=timedelta(minutes=15),
                    unit=unit,
                )
            )
    db.session.flush()

    original_flex_context = house.flex_context.copy()

    # --- Act ---
    house_copy = copy_asset(house, account=supplier_account)

    # 1. Correct account and name.
    assert house_copy.account_id == supplier_account.id
    assert house_copy.name == f"{house.name} (Copy)"

    # 2. Top-level in the target account (no parent given → parent_asset_id = None).
    assert house_copy.parent_asset_id is None

    # 4. Direct sensors on the copied asset are duplicated.
    copied_house_sensors = db.session.scalars(
        select(Sensor).filter(Sensor.generic_asset_id == house_copy.id)
    ).all()
    assert len(copied_house_sensors) == 1
    copied_site_capacity_sensor = copied_house_sensors[0]
    assert copied_site_capacity_sensor.name == site_capacity_sensor.name
    assert copied_site_capacity_sensor.unit == site_capacity_sensor.unit
    assert (
        copied_site_capacity_sensor.event_resolution
        == site_capacity_sensor.event_resolution
    )

    # 3. flex_context: the internal sensor reference (site-power-capacity) is
    #    updated to the new copied sensor ID; the external reference
    #    (consumption-price on the public epex asset) is preserved as-is.
    assert (
        house_copy.flex_context["consumption-price"]
        == original_flex_context["consumption-price"]
    ), "External sensor reference must be unchanged"
    assert house_copy.flex_context["site-power-capacity"] == {
        "sensor": copied_site_capacity_sensor.id
    }, "Internal sensor reference must point to the new copied sensor"
    assert (
        house_copy.flex_context["site-power-capacity"]["sensor"]
        != site_capacity_sensor.id
    ), "Internal sensor reference must not point to the original sensor"

    # 5. Deep copy for hierarchy: original child assets are duplicated.
    children_of_copy = db.session.scalars(
        select(GenericAsset).filter_by(parent_asset_id=house_copy.id)
    ).all()
    assert len(children_of_copy) == 2
    assert sorted(child.name for child in children_of_copy) == [
        "EV charger 1",
        "EV charger 2",
    ]

    # 6. Sensors on copied child assets are also duplicated.
    copied_child_ids = [child.id for child in children_of_copy]
    copied_child_sensors = db.session.scalars(
        select(Sensor).filter(Sensor.generic_asset_id.in_(copied_child_ids))
    ).all()
    assert len(copied_child_sensors) == 4


def test_copy_asset_replaces_sensor_refs_in_config(
    setup_api_test_data, setup_accounts, setup_markets, setup_generic_asset_types, db
):
    """
    When copying an asset, sensor references inside flex_context, flex_model and
    sensors_to_show must be updated to point to the newly copied sensors.

    Sensor references that belong to PUBLIC assets (account_id=None, e.g. a public
    price sensor) must be left unchanged.

    Sensor references that belong to PRIVATE assets not in the copied subtree must
    be removed from the config.

    Asset layout:

    Battery  (EMS, Prosumer account)
    ├── sensor_internal  – belongs to Battery, referenced in flex_context
    ├── flex_context:
    │     "consumption-capacity": {"sensor": <sensor_internal.id>}   ← internal (copied)
    │     "production-price":     {"sensor": <price_sensor.id>}      ← external public
    │     "private-external":     {"sensor": <private_ext_sensor.id>}← external private → removed
    ├── flex_model:
    │     "soc-min": "700.0 kWh"                                     ← no sensor
    │     "consumption-capacity": {"sensor": <sensor_internal.id>}   ← internal (copied)
    ├── sensors_to_show:
    │     [{"title": "Chart", "plots": [
    │         {"sensor": <sensor_internal.id>},                       ← internal (copied)
    │         {"sensors": [<sensor_internal.id>, <price_sensor.id>,   ← mixed: internal/public/private
    │                      <private_ext_sensor.id>]}
    │     ]}]

    After copying:
    - References to sensor_internal        → replaced with new copied sensor's ID
    - References to price_sensor (public)  → unchanged
    - References to private_ext_sensor     → removed entirely
    """
    prosumer_account = setup_accounts["Prosumer"]
    supplier_account = setup_accounts["Supplier"]
    price_sensor = setup_markets["epex_da"]
    assert price_sensor.generic_asset.account_id is None, "epex must be a public asset"

    asset_type = setup_generic_asset_types["battery"]

    # A private sensor on a different account's asset (Supplier), NOT in the copy subtree.
    # Use integer IDs (not ORM object references) to avoid SQLAlchemy cascade
    # issues with potentially-detached session objects from earlier tests.
    supplier_asset = GenericAsset(
        name="Supplier asset for private sensor ref test",
        generic_asset_type_id=asset_type.id,
        account_id=supplier_account.id,
    )
    db.session.add(supplier_asset)
    db.session.flush()
    private_ext_sensor = Sensor(
        name="private external sensor",
        generic_asset=supplier_asset,
        event_resolution=timedelta(minutes=15),
        unit="kW",
    )
    db.session.add(private_ext_sensor)
    db.session.flush()

    battery = GenericAsset(
        name="Battery for sensor ref test",
        generic_asset_type_id=asset_type.id,
        account_id=prosumer_account.id,
    )
    db.session.add(battery)
    db.session.flush()

    sensor_internal = Sensor(
        name="internal sensor",
        generic_asset=battery,
        event_resolution=timedelta(minutes=15),
        unit="kW",
    )
    db.session.add(sensor_internal)
    db.session.flush()

    battery.flex_context = {
        "consumption-capacity": {"sensor": sensor_internal.id},
        "production-price": {"sensor": price_sensor.id},
        "private-external": {"sensor": private_ext_sensor.id},
    }
    battery.flex_model = {
        "soc-min": "700.0 kWh",
        "consumption-capacity": {"sensor": sensor_internal.id},
    }
    battery.sensors_to_show = [
        {
            "title": "Chart",
            "plots": [
                {"sensor": sensor_internal.id},
                {
                    "sensors": [
                        sensor_internal.id,
                        price_sensor.id,
                        private_ext_sensor.id,
                    ]
                },
            ],
        }
    ]
    db.session.flush()

    # --- Act ---
    battery_copy = copy_asset(battery, account=prosumer_account)

    # Locate the new copied sensor.
    copied_sensors = db.session.scalars(
        select(Sensor).filter(Sensor.generic_asset_id == battery_copy.id)
    ).all()
    assert len(copied_sensors) == 1
    new_sensor = copied_sensors[0]
    assert new_sensor.id != sensor_internal.id

    # flex_context: internal replaced, public external preserved, private external removed.
    assert battery_copy.flex_context["consumption-capacity"] == {
        "sensor": new_sensor.id
    }
    assert battery_copy.flex_context["production-price"] == {"sensor": price_sensor.id}
    assert "private-external" not in battery_copy.flex_context

    # flex_model: internal replaced, plain string preserved.
    assert battery_copy.flex_model["consumption-capacity"] == {"sensor": new_sensor.id}
    assert battery_copy.flex_model["soc-min"] == "700.0 kWh"

    # sensors_to_show: single-sensor plot with private external is removed from plots;
    # multi-sensor list has private external ID filtered out.
    chart = battery_copy.sensors_to_show[0]
    assert chart["plots"][0] == {"sensor": new_sensor.id}
    assert chart["plots"][1] == {"sensors": [new_sensor.id, price_sensor.id]}

    # Original asset config must not be mutated.
    assert battery.flex_context["consumption-capacity"] == {
        "sensor": sensor_internal.id
    }
    assert battery.flex_model["consumption-capacity"] == {"sensor": sensor_internal.id}


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_copy_asset_api_copies_direct_sensors(
    client, setup_api_test_data, setup_accounts, requesting_user, db
):
    """Copying an asset through the API should also duplicate its direct sensors."""
    prosumer_account = setup_accounts["Prosumer"]
    source_asset = db.session.scalars(
        select(GenericAsset).filter_by(
            account_id=prosumer_account.id,
            name="Test grid connected battery storage",
        )
    ).first()
    assert source_asset is not None

    source_sensor = Sensor(
        name="copy-api-source-sensor",
        generic_asset=source_asset,
        event_resolution=timedelta(minutes=15),
        unit="kW",
    )
    db.session.add(source_sensor)
    db.session.flush()

    response = client.post(url_for("AssetAPI:copy_assets", id=source_asset.id))
    assert response.status_code == 201

    copied_asset_id = response.json["asset"]
    copied_asset = db.session.get(GenericAsset, copied_asset_id)
    assert copied_asset is not None
    copied_sensor = db.session.scalars(
        select(Sensor).filter(
            Sensor.generic_asset_id == copied_asset_id,
            Sensor.name == source_sensor.name,
        )
    ).first()

    assert copied_sensor is not None
    assert copied_sensor.unit == source_sensor.unit
    assert copied_sensor.event_resolution == source_sensor.event_resolution

    check_audit_log_event(
        db=db,
        event=(
            f"Copied asset '{source_asset.name}': {source_asset.id} "
            f"to '{copied_asset.name}': {copied_asset.id}"
        ),
        user=requesting_user,
        asset=copied_asset,
    )
