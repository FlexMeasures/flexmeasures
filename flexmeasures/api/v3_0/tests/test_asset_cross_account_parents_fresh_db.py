"""Asset trees may span organisations, by permission.

An asset may be placed under a parent asset in another organisation (account) by a user who may add assets
under that parent (create-children) and create assets in the asset's own organisation (create-children on the account,
or being an admin, for a public asset). Deleting an asset deletes its children in other organisations, too,
so that needs permission to delete them, too.

1.0.x: the API lets non-admins create assets only in their own account (GenericAssetSchema.validate_account),
and asset deletion needs the "delete" permission (account-admins and consultants).
"""

from __future__ import annotations

import pytest
from flask import url_for
from sqlalchemy import select

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.user import Account

ACCOUNTS = ("Prosumer", "Supplier", "Consultancy", "ConsultancyClient")


@pytest.fixture
def sites(fresh_db, setup_api_fresh_test_data) -> dict[str, int]:
    """A site in each of the four accounts, by account name, and the account ids under "<name> account"."""
    db = fresh_db
    asset_type = db.session.execute(select(GenericAssetType)).scalars().first()
    ids = {}
    for name in ACCOUNTS:
        account = db.session.execute(
            select(Account).filter_by(name=f"Test {name} Account")
        ).scalar_one()
        site = GenericAsset(
            name=f"{name} site", generic_asset_type=asset_type, owner=account
        )
        db.session.add(site)
        db.session.flush()
        ids[name] = site.id
        ids[f"{name} account"] = account.id
    ids["asset type"] = asset_type.id
    db.session.commit()
    return ids


def _post_data(sites: dict, name: str, parent: str, account: str | None) -> dict:
    post_data = {
        "name": name,
        "latitude": 52.0,
        "longitude": 5.0,
        "generic_asset_type_id": sites["asset type"],
        "parent_asset_id": sites[parent],
    }
    if account is not None:
        post_data["account_id"] = sites[f"{account} account"]
    return post_data


OTHER_ORGANISATION = "belongs to another organisation"
NOT_OWN_ACCOUNT = "not allowed to create assets for this account"  # 1.0.x: non-admins create only in their own account


@pytest.mark.parametrize(
    "requesting_user, parent, account, expected_status, expected_message",
    [
        # 1.0.x: the API lets a consultant create assets only in their own organisation (not for a client),
        (
            "test_consultant@seita.nl",
            "Consultancy",
            "ConsultancyClient",
            422,
            NOT_OWN_ACCOUNT,
        ),
        # ... and not in their own organisation, under a client's asset, without being its account-admin.
        (
            "test_consultant@seita.nl",
            "ConsultancyClient",
            "Consultancy",
            422,
            OTHER_ORGANISATION,
        ),
        # An account-admin may not add assets under another organisation's asset,
        (
            "test_prosumer_user_2@seita.nl",
            "Supplier",
            "Prosumer",
            422,
            OTHER_ORGANISATION,
        ),
        # ... nor create assets in another organisation.
        ("test_prosumer_user_2@seita.nl", "Prosumer", "Supplier", 422, NOT_OWN_ACCOUNT),
        # A public asset under a private parent: only for admins.
        ("test_prosumer_user_2@seita.nl", "Prosumer", None, 422, OTHER_ORGANISATION),
        # A member (not an account-admin) may not add an asset of their own account under another organisation's asset, either.
        (
            "test_prosumer_user@seita.nl",
            "Supplier",
            "Prosumer",
            422,
            OTHER_ORGANISATION,
        ),
        ("test_admin_user@seita.nl", "Prosumer", None, 201, None),
        ("test_admin_user@seita.nl", "Supplier", "Prosumer", 201, None),
    ],
    indirect=["requesting_user"],
)
def test_create_asset_under_a_parent_in_another_account(
    client,
    fresh_db,
    sites,
    requesting_user,
    parent,
    account,
    expected_status,
    expected_message,
):
    post_data = _post_data(sites, "cross-account child", parent, account)

    response = client.post(url_for("AssetAPI:post"), json=post_data)

    assert response.status_code == expected_status, response.json
    created = fresh_db.session.execute(
        select(GenericAsset).filter_by(name="cross-account child")
    ).scalar_one_or_none()
    if expected_status == 201:
        assert created.parent_asset_id == sites[parent]
        assert created.account_id == (
            sites[f"{account} account"] if account is not None else None
        )
    else:
        assert created is None
        assert expected_message in str(response.json["message"])


@pytest.mark.parametrize(
    "requesting_user, child_account, new_parent, expected_status",
    [
        ("test_consultant@seita.nl", "ConsultancyClient", "Consultancy", 200),
        ("test_prosumer_user_2@seita.nl", "Prosumer", "Supplier", 422),
        ("test_prosumer_user@seita.nl", "Prosumer", "Supplier", 422),
        ("test_admin_user@seita.nl", "Prosumer", "Supplier", 200),
    ],
    indirect=["requesting_user"],
)
def test_patch_asset_parent_in_another_account(
    client,
    fresh_db,
    sites,
    requesting_user,
    child_account,
    new_parent,
    expected_status,
):
    child = GenericAsset(
        name="asset to move",
        generic_asset_type_id=sites["asset type"],
        account_id=sites[f"{child_account} account"],
    )
    fresh_db.session.add(child)
    fresh_db.session.commit()
    child_id = child.id

    response = client.patch(
        url_for("AssetAPI:patch", id=child_id),
        json={"parent_asset_id": sites[new_parent]},
    )

    assert response.status_code == expected_status, response.json
    fresh_db.session.expire_all()
    stored_parent = fresh_db.session.get(GenericAsset, child_id).parent_asset_id
    assert stored_parent == (sites[new_parent] if expected_status == 200 else None)


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_edit_an_asset_that_has_a_parent_in_another_account(
    client, fresh_db, sites, requesting_user
):
    """A member of the child's organisation can edit it, as long as they leave its parent (which they may not read) as it is."""
    child = GenericAsset(
        name="supplier asset under a prosumer site",
        generic_asset_type_id=sites["asset type"],
        account_id=sites["Supplier account"],
        parent_asset_id=sites["Prosumer"],  # as set by an admin
    )
    fresh_db.session.add(child)
    fresh_db.session.commit()
    child_id = child.id

    # Sending the unchanged parent along, as the UI's edit form does
    response = client.patch(
        url_for("AssetAPI:patch", id=child_id),
        json={"name": "renamed", "parent_asset_id": sites["Prosumer"]},
    )
    assert response.status_code == 200, response.json
    fresh_db.session.expire_all()
    child = fresh_db.session.get(GenericAsset, child_id)
    assert child.name == "renamed"
    assert child.parent_asset_id == sites["Prosumer"]

    # Leaving the parent out
    response = client.patch(
        url_for("AssetAPI:patch", id=child_id), json={"name": "renamed again"}
    )
    assert response.status_code == 200, response.json
    fresh_db.session.expire_all()
    child = fresh_db.session.get(GenericAsset, child_id)
    assert child.name == "renamed again"
    assert child.parent_asset_id == sites["Prosumer"]

    # Moving it under another asset of another organisation is still refused
    response = client.patch(
        url_for("AssetAPI:patch", id=child_id),
        json={"parent_asset_id": sites["Consultancy"]},
    )
    assert response.status_code == 422, response.json


@pytest.mark.parametrize(
    "requesting_user, parent, child_account, expected_status",
    [
        # The Prosumer account-admin may not delete the Supplier child that deleting the parent would delete.
        ("test_prosumer_user_2@seita.nl", "Prosumer", "Supplier", 403),
        # A public child under a private parent may only be deleted by an admin.
        ("test_prosumer_user_2@seita.nl", "Prosumer", None, 403),
        # A consultant may delete a client's asset, but not a child of it in the consultancy itself
        # (1.0.x: deleting assets needs the "delete" permission, which only the consultancy's account-admins have there).
        ("test_consultant@seita.nl", "ConsultancyClient", "Consultancy", 403),
        ("test_admin_user@seita.nl", "Prosumer", "Supplier", 204),
        ("test_admin_user@seita.nl", "Prosumer", None, 204),
    ],
    indirect=["requesting_user"],
)
def test_delete_asset_with_children_in_another_account(
    client, fresh_db, sites, requesting_user, parent, child_account, expected_status
):
    child = GenericAsset(
        name="child in another organisation",
        generic_asset_type_id=sites["asset type"],
        account_id=sites[f"{child_account} account"] if child_account else None,
        parent_asset_id=sites[parent],
    )
    fresh_db.session.add(child)
    fresh_db.session.commit()
    child_id = child.id

    response = client.delete(url_for("AssetAPI:delete", id=sites[parent]))

    assert response.status_code == expected_status, response.json
    fresh_db.session.expire_all()
    if expected_status == 204:
        assert fresh_db.session.get(GenericAsset, sites[parent]) is None
        assert fresh_db.session.get(GenericAsset, child_id) is None
    else:
        assert fresh_db.session.get(GenericAsset, sites[parent]) is not None
        assert fresh_db.session.get(GenericAsset, child_id) is not None


@pytest.mark.parametrize(
    "requesting_user, source, account, parent, expected_status",
    [
        # A consultant may copy a client's asset under their own organisation's asset, keeping it in the client's organisation.
        (
            "test_consultant@seita.nl",
            "ConsultancyClient",
            "ConsultancyClient",
            "Consultancy",
            201,
        ),
        # An account-admin may not copy their own asset under another organisation's asset.
        ("test_prosumer_user_2@seita.nl", "Prosumer", "Prosumer", "Supplier", 403),
    ],
    indirect=["requesting_user"],
)
def test_copy_asset_under_a_parent_in_another_account(
    client, fresh_db, sites, requesting_user, source, account, parent, expected_status
):
    response = client.post(
        url_for(
            "AssetAPI:copy_assets",
            id=sites[source],
            account=sites[f"{account} account"],
            parent=sites[parent],
        )
    )
    assert response.status_code == expected_status, response.json
    if expected_status == 201:
        copied = fresh_db.session.get(GenericAsset, response.json["asset"])
        assert copied.parent_asset_id == sites[parent]
        assert copied.account_id == sites[f"{account} account"]
