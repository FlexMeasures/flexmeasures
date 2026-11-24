"""An asset's parent cannot be the asset itself or one of its descendants.

A cycle in the asset tree would make every later walk up or down the tree run forever.
"""

from __future__ import annotations

import pytest
from flask import url_for
from marshmallow import ValidationError
from sqlalchemy import select

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.user import Account
from flexmeasures.data.services.generic_assets import patch_asset


@pytest.fixture
def asset_chain(fresh_db, setup_api_fresh_test_data):
    """Three assets in the Prosumer account: grandparent > parent > child, and a separate site."""
    db = fresh_db
    account = db.session.execute(
        select(Account).filter_by(name="Test Prosumer Account")
    ).scalar_one()
    asset_type = db.session.execute(select(GenericAssetType)).scalars().first()
    grandparent = GenericAsset(
        name="grandparent", generic_asset_type=asset_type, owner=account
    )
    parent = GenericAsset(
        name="parent",
        generic_asset_type=asset_type,
        owner=account,
        parent_asset=grandparent,
    )
    child = GenericAsset(
        name="child", generic_asset_type=asset_type, owner=account, parent_asset=parent
    )
    other_site = GenericAsset(
        name="other site", generic_asset_type=asset_type, owner=account
    )
    db.session.add_all([grandparent, parent, child, other_site])
    db.session.commit()
    return {asset.name: asset.id for asset in (grandparent, parent, child, other_site)}


@pytest.mark.parametrize("new_parent", ["child", "parent"])
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_patch_asset_api_refuses_a_descendant_as_parent(
    client, fresh_db, asset_chain, requesting_user, new_parent
):
    response = client.patch(
        url_for("AssetAPI:patch", id=asset_chain["grandparent"]),
        json={"parent_asset_id": asset_chain[new_parent]},
    )
    assert response.status_code == 422, response.json
    assert "descendants" in str(response.json)
    assert (
        fresh_db.session.get(GenericAsset, asset_chain["grandparent"]).parent_asset_id
        is None
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_patch_asset_api_accepts_a_parent_outside_the_subtree(
    client, fresh_db, asset_chain, requesting_user
):
    response = client.patch(
        url_for("AssetAPI:patch", id=asset_chain["grandparent"]),
        json={"parent_asset_id": asset_chain["other site"]},
    )
    assert response.status_code == 200, response.json
    assert (
        fresh_db.session.get(GenericAsset, asset_chain["grandparent"]).parent_asset_id
        == asset_chain["other site"]
    )


def test_patch_asset_refuses_itself_or_a_descendant_as_parent(fresh_db, asset_chain):
    """patch_asset itself refuses the cycle, so the UI edit form (and any other caller) cannot create one either."""
    parent = fresh_db.session.get(GenericAsset, asset_chain["parent"])
    for new_parent in ("parent", "child"):
        with pytest.raises(ValidationError, match="descendants"):
            patch_asset(parent, {"parent_asset_id": asset_chain[new_parent]})
    assert parent.parent_asset_id == asset_chain["grandparent"]

    patch_asset(parent, {"parent_asset_id": asset_chain["other site"]})
    assert parent.parent_asset_id == asset_chain["other site"]
