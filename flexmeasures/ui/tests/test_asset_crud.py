from flask import url_for

import pytest
import json
import copy

from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.ui.tests.utils import (
    mock_asset_data,
    mock_asset_data_with_kpis,
    mock_asset_data_as_form_input,
)

"""
Testing if our asset UI proceeds with the expected round trip.
Here, we mock the API responses (we have to, as our UI layer contacts FlexMeasures as a server, which does not run during tests).
The real logic tests are done in the api package, which is also the better place for that.
"""

api_path_assets = "http://localhost//api/v3_0/assets"


def test_assets_page_empty(db, client, as_prosumer_user1):
    asset_index = client.get(url_for("AssetCrudUI:index"), follow_redirects=True)
    assert asset_index.status_code == 200


def test_new_asset_page(client, setup_assets, as_admin):
    asset_page = client.get(url_for("AssetCrudUI:get", id="new"), follow_redirects=True)
    assert asset_page.status_code == 200
    assert b"Creating a new asset" in asset_page.data


@pytest.mark.parametrize(
    "view",
    [
        "get",  # tests redirect to context
        "context",
        "graphs",
        "properties",
        "auditlog",
    ],
)
def test_asset_page(db, client, setup_assets, as_prosumer_user1, view):
    user = find_user_by_email("test_prosumer_user@seita.nl")
    asset = user.account.generic_assets[0]
    db.session.expunge(user)

    asset_page = client.get(
        url_for(
            f"AssetCrudUI:{view}",
            id=asset.id,
            start_time="2022-10-01T00:00:00+02:00",
            end_time="2022-10-02T00:00:00+02:00",
        ),
        follow_redirects=True,
    )
    assert asset_page.status_code == 200
    if view in ("get", "context"):
        assert "Show sensors".encode() in asset_page.data
        assert "Edit flex-context".encode() in asset_page.data
        assert "Structure".encode() in asset_page.data
        assert "Location".encode() in asset_page.data


@pytest.mark.parametrize(
    "args, error",
    [
        (
            {"start_time": "2022-10-01T00:00:00+02:00"},
            "Both start_time and end_time must be provided together.",
        ),
        (
            {"end_time": "2022-10-01T00:00:00+02:00"},
            "Both start_time and end_time must be provided together.",
        ),
        (
            {
                "start_time": "2022-10-01T00:00:00+02:00",
                "end_time": "2022-10-01T00:00:00+02:00",
            },
            "start_time must be before end_time.",
        ),
        (
            {
                "start_time": "2022-10-01T00:00:00",
                "end_time": "2022-10-02T00:00:00+02:00",
            },
            "Not a valid aware datetime",
        ),
    ],
)
def test_asset_page_dates_validation(
    db, client, setup_assets, as_prosumer_user1, args, error
):
    user = find_user_by_email("test_prosumer_user@seita.nl")
    asset = user.account.generic_assets[0]
    db.session.expunge(user)

    asset_page = client.get(
        url_for(
            "AssetCrudUI:graphs",
            id=asset.id,
            **args,
        ),
        follow_redirects=True,
    )
    assert error.encode() in asset_page.data
    assert "UNPROCESSABLE_ENTITY".encode() in asset_page.data


def test_add_asset(db, client, setup_assets, as_admin):
    """Add a new asset"""
    user = find_user_by_email("test_prosumer_user@seita.nl")
    mock_asset = mock_asset_data(account_id=user.account.id, as_list=False)

    response = client.post(
        url_for("AssetCrudUI:post", id="create"),
        follow_redirects=True,
        data=mock_asset_data_as_form_input(mock_asset),
    )
    assert response.status_code == 200  # response is HTML form
    assert "html" in response.content_type
    assert b"Creation was successful" in response.data
    assert mock_asset["name"] in str(response.data)
    assert str(mock_asset["latitude"]) in str(response.data)
    assert str(mock_asset["longitude"]) in str(response.data)


def test_edit_asset(db, client, setup_assets, as_admin):
    mock_asset = mock_asset_data_with_kpis(db=db, as_list=False)
    mock_asset["name"] = "Edited name"

    response = client.post(
        url_for("AssetCrudUI:post", id=1),
        follow_redirects=True,
        data=mock_asset_data_as_form_input(mock_asset),
    )
    assert response.status_code == 200
    assert b"Editing was successful" in response.data
    assert mock_asset["name"] in str(response.data)
    assert str(mock_asset["latitude"]) in str(response.data)
    assert str(mock_asset["longitude"]) in str(response.data)


def test_sensors_to_show_as_kpis_json(db, client, setup_assets, as_admin):
    mock_asset = mock_asset_data_with_kpis(db=db, as_list=False)

    # Test asset with invalid json
    ma_copy = copy.deepcopy(mock_asset)
    ma_copy["sensors_to_show_as_kpis"] = "not a json."
    response = client.post(
        url_for("AssetCrudUI:post", id=1),
        follow_redirects=True,
        data=mock_asset_data_as_form_input(ma_copy),
    )
    # how the UI works is that the page reloads with 200 but there is a an error message string that checks if the editing was successful or not
    assert response.status_code == 200
    assert b"Cannot edit asset:" in response.data
    assert b"Invalid JSON" in response.data

    # Test invalid function in the sensors_to_show_as_kpis
    ma_copy = copy.deepcopy(mock_asset)
    ma_copy["sensors_to_show_as_kpis"] = json.loads(ma_copy["sensors_to_show_as_kpis"])
    ma_copy["sensors_to_show_as_kpis"][0]["function"] = "not valid function"
    # Stringify the sensors_to_show_as_kpis
    ma_copy["sensors_to_show_as_kpis"] = json.dumps(ma_copy["sensors_to_show_as_kpis"])
    response = client.post(
        url_for("AssetCrudUI:post", id=1),
        follow_redirects=True,
        data=mock_asset_data_as_form_input(ma_copy),
    )
    assert response.status_code == 200
    assert b"Cannot edit asset:" in response.data
    assert b"Must be one of: sum, min, max, mean." in response.data


def test_delete_asset(client, db, as_admin, setup_assets):
    """Deleting a top-level asset redirects to the asset index and shows a toast."""
    assets = list(setup_assets.values())
    top_level = next(
        (a for a in assets if a.parent_asset_id is None),
        None,
    )
    assert top_level is not None, "No top-level asset found in fixtures"
    response = client.get(
        url_for("AssetCrudUI:delete_with_data", id=top_level.id),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"have been deleted" in response.data


def test_delete_child_asset_redirects_to_parent(
    client, db, as_admin, setup_accounts, setup_generic_asset_types
):
    """Deleting a child asset should redirect to the parent asset's context page."""
    parent = GenericAsset(
        name="parent-for-deletion-test",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Prosumer"],
        latitude=10,
        longitude=100,
    )
    db.session.add(parent)
    db.session.flush()

    child = GenericAsset(
        name="child-for-deletion-test",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Prosumer"],
        latitude=10,
        longitude=100,
        parent_asset_id=parent.id,
    )
    db.session.add(child)
    db.session.commit()

    response = client.get(
        url_for("AssetCrudUI:delete_with_data", id=child.id),
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert url_for("AssetCrudUI:context", id=parent.id) in response.location


# ---------------------------------------------------------------------------
# Permission tests for the asset properties page
#
# ACL summary used by the tests below:
#   - GenericAsset.update    → any member of the owning account (+ consultants)
#   - GenericAsset.delete    → account-admin or consultant only
#   - GenericAsset.create-children (child assets/sensors) → any account member
#   - Account.create-children (top-level assets) → account-admin or consultant
#
# "user_can_create_assets" (Account.create-children) gates:
#   • The "Create asset" child-asset button on the properties page
#   • The "Copy this asset" / "Copy to my account" copy buttons
# "user_can_update_asset" (GenericAsset.update) gates the "Edit asset" sidepanel.
# "user_can_delete_asset" (GenericAsset.delete) gates the "Delete this asset" button.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "login_fixture, expect_copy_sibling, expect_copy_to_own",
    [
        # Site admin can create any asset → sibling copy
        ("as_admin", True, False),
        # Account-admin of same account → sibling copy
        ("as_prosumer_account_admin", True, False),
        # Plain account member: cannot create a top-level sibling,
        # and asset is already in their own account so "copy to own" is also False.
        ("as_prosumer_user1", False, False),
    ],
)
def test_copy_button_visibility_own_account_asset(
    db,
    client,
    setup_assets,
    request,
    login_fixture,
    expect_copy_sibling,
    expect_copy_to_own,
):
    """
    The copy-asset buttons on the properties page respect account-level
    'create-children' permissions.

    Only account-admins (and site admins) can create top-level assets, so
    only they should see the copy button for an asset that already belongs
    to their account.  Plain users see neither button.
    """
    from flexmeasures.data.services.users import find_user_by_email

    user = find_user_by_email("test_prosumer_user@seita.nl")
    asset_id = user.account.generic_assets[0].id
    db.session.expunge(user)

    request.getfixturevalue(login_fixture)

    page = client.get(
        url_for("AssetCrudUI:properties", id=asset_id),
        follow_redirects=True,
    )
    assert page.status_code == 200

    if expect_copy_sibling:
        assert b"Copy this asset" in page.data
        assert b"Copy to my account" not in page.data
    elif expect_copy_to_own:
        assert b"Copy to my account" in page.data
        assert b"Copy this asset" not in page.data
    else:
        assert b"Copy this asset" not in page.data
        assert b"Copy to my account" not in page.data


def test_copy_to_own_account_button_for_cross_account_admin(
    db, client, public_asset, as_dummy_account_admin
):
    """
    An account-admin of a *different* account viewing a public asset should see
    'Copy to my account' (they cannot create a public sibling, but they can
    create an asset in their own account).
    """
    page = client.get(
        url_for("AssetCrudUI:properties", id=public_asset.id),
        follow_redirects=True,
    )
    assert page.status_code == 200
    assert b"Copy to my account" in page.data
    assert b"Copy this asset" not in page.data


@pytest.mark.parametrize(
    "login_fixture, expect_edit_panel",
    [
        # Site admin can update any asset.
        ("as_admin", True),
        # Account-admin of same account.
        ("as_prosumer_account_admin", True),
        # Plain account member: GenericAsset.update is open to all account
        # members by design, so the edit sidepanel IS shown.
        ("as_prosumer_user1", True),
    ],
)
def test_edit_panel_visibility_on_properties_page(
    db, client, setup_assets, request, login_fixture, expect_edit_panel
):
    """
    The 'Edit asset' sidepanel is gated on GenericAsset.update, which is
    intentionally open to every member of the owning account (not just admins).
    """
    from flexmeasures.data.services.users import find_user_by_email

    user = find_user_by_email("test_prosumer_user@seita.nl")
    asset_id = user.account.generic_assets[0].id
    db.session.expunge(user)

    request.getfixturevalue(login_fixture)

    page = client.get(
        url_for("AssetCrudUI:properties", id=asset_id),
        follow_redirects=True,
    )
    assert page.status_code == 200
    if expect_edit_panel:
        assert b"Edit asset" in page.data
    else:
        assert b"Edit asset" not in page.data


@pytest.mark.parametrize(
    "login_fixture, expect_delete_btn, expect_create_asset_btn",
    [
        # Site admin: can delete and create top-level assets.
        ("as_admin", True, True),
        # Account-admin of same account: same rights.
        ("as_prosumer_account_admin", True, True),
        # Plain account member: cannot delete or create top-level assets.
        ("as_prosumer_user1", False, False),
    ],
)
def test_admin_only_buttons_on_properties_page(
    db,
    client,
    setup_assets,
    request,
    login_fixture,
    expect_delete_btn,
    expect_create_asset_btn,
):
    """
    'Delete this asset' and 'Create asset' (child asset via account) are
    gated on account-admin permissions and must not appear for plain users.
    """
    from flexmeasures.data.services.users import find_user_by_email

    user = find_user_by_email("test_prosumer_user@seita.nl")
    asset_id = user.account.generic_assets[0].id
    db.session.expunge(user)

    request.getfixturevalue(login_fixture)

    page = client.get(
        url_for("AssetCrudUI:properties", id=asset_id),
        follow_redirects=True,
    )
    assert page.status_code == 200

    if expect_delete_btn:
        assert b"Delete this asset" in page.data
    else:
        assert b"Delete this asset" not in page.data

    if expect_create_asset_btn:
        assert b"Create asset" in page.data
    else:
        assert b"Create asset" not in page.data
