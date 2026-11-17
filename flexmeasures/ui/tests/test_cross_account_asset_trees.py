"""Asset trees may span organisations: the UI shows only what the viewer may read.

A parent asset (or ancestor) the viewer may not read shows as "(another organisation)", without its name or a link,
and flex-context values inherited from it are not shown. A parent organisation's tree marks children of other organisations.
Like Felix's own case, a public asset (no account) under a private parent is covered, too.

1.0.x: the tree is drawn by the show_tree macro (no asset-tree.js); its node list is now JSON-encoded.
"""

from __future__ import annotations

import json
import re

import pytest
from flask import url_for

from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.ui.tests.utils import login, logout, mock_asset_data_as_form_input

PARENT_CAPACITY = "1234 kW"


@pytest.fixture
def as_supplier_user(client):
    login(client, "test_supplier_user_4@seita.nl", "testtest")
    yield
    logout(client)


@pytest.fixture
def tree(db, setup_accounts, setup_roles_users, setup_generic_asset_types):
    """A Prosumer site with a flex-context, a Supplier asset and a public asset under it."""
    asset_type = setup_generic_asset_types["battery"]
    parent = GenericAsset(
        name="Prosumer secret site",
        generic_asset_type=asset_type,
        owner=setup_accounts["Prosumer"],
        flex_context={"site-power-capacity": PARENT_CAPACITY},
    )
    db.session.add(parent)
    db.session.flush()
    supplier_child = GenericAsset(
        name="Supplier child",
        generic_asset_type=asset_type,
        owner=setup_accounts["Supplier"],
        parent_asset_id=parent.id,
    )
    public_child = GenericAsset(
        name="Public child",
        generic_asset_type=asset_type,
        parent_asset_id=parent.id,
    )
    db.session.add_all([supplier_child, public_child])
    db.session.commit()
    ids = dict(parent=parent.id, supplier=supplier_child.id, public=public_child.id)
    yield ids
    db.session.rollback()
    for asset_id in (ids["supplier"], ids["public"], ids["parent"]):
        asset = db.session.get(GenericAsset, asset_id)
        if asset is not None:
            db.session.delete(asset)
    db.session.commit()


def _tree_nodes(page: bytes) -> list[dict]:
    """The assets the context page draws in its tree."""
    match = re.search(rb"let assets = (\[.*?\]);\n", page, re.DOTALL)
    assert match, "no asset tree on the page"
    return json.loads(match.group(1))


def _inherited_flex_context(page: bytes) -> dict:
    match = re.search(rb"const inheritedFlexContext = (\{.*?\});\n", page)
    assert match, "no inherited flex-context on the page"
    return json.loads(match.group(1))


def _context_page(client, asset_id: int) -> bytes:
    response = client.get(url_for("AssetCrudUI:context", id=asset_id))
    assert response.status_code == 200
    return response.data


@pytest.mark.parametrize("child", ["supplier", "public"])
def test_unreadable_parent_shows_as_another_organisation(
    client, tree, as_supplier_user, child
):
    """A Supplier user may read the Supplier child and the public child, but not their Prosumer parent."""
    page = _context_page(client, tree[child])

    assert b"(another organisation)" in page
    assert b"Prosumer secret site" not in page
    assert f"/assets/{tree['parent']}".encode() not in page
    # Not in the breadcrumb, nor in the tree
    nodes = _tree_nodes(page)
    assert all(node["id"] != tree["parent"] for node in nodes)
    (hidden_parent,) = [
        node for node in nodes if node["name"] == "(another organisation)"
    ]
    assert hidden_parent["link"] is None
    assert hidden_parent["sensors"] == []
    (child_node,) = [node for node in nodes if node["id"] == tree[child]]
    assert child_node["parent"] == hidden_parent["id"]
    assert child_node["other_organisation"] is True
    # The inherited flex-context value is not shown, but the page says there is one
    assert PARENT_CAPACITY.encode() not in page
    inherited = _inherited_flex_context(page)
    assert inherited["site-power-capacity"] == {
        "value": None,
        "hidden": True,
        "asset_id": None,
        "asset_name": "(another organisation)",
    }
    # The graphs page looks up sensors only up to the highest asset the viewer may read
    response = client.get(url_for("AssetCrudUI:graphs", id=tree[child]))
    assert response.status_code == 200
    assert f"asset_id={tree['parent']}".encode() not in response.data
    assert f"asset_id={tree[child]}".encode() in response.data


def test_readable_parent_is_shown(client, tree, as_prosumer_user1):
    """A Prosumer user may read the parent and the public child, so sees the parent and the inherited value."""
    page = _context_page(client, tree["public"])

    assert b"Prosumer secret site" in page
    # The sibling in another organisation is not listed (e.g. in the breadcrumb's dropdown)
    assert b"Supplier child" not in page
    inherited = _inherited_flex_context(page)
    assert inherited["site-power-capacity"]["value"] == PARENT_CAPACITY
    assert inherited["site-power-capacity"]["asset_id"] == tree["parent"]


def test_parent_tree_marks_children_of_other_organisations(
    client, tree, as_prosumer_user1
):
    """The parent organisation's tree marks the public child, and shows the Supplier child (which it may not read) only as another organisation's."""
    nodes = {
        str(node["id"]): node
        for node in _tree_nodes(_context_page(client, tree["parent"]))
    }

    public_child = nodes[str(tree["public"])]
    assert public_child["other_organisation"] is True
    assert public_child["tooltip"]["Organisation"] == "Public"
    assert str(tree["supplier"]) not in nodes
    hidden = nodes[f"hidden-children-of-{tree['parent']}"]
    assert hidden["name"] == "(another organisation)"
    assert hidden["parent"] == tree["parent"]
    assert b"Supplier child" not in _context_page(client, tree["parent"])


def test_admin_sees_the_whole_tree_marked(client, tree, as_admin):
    nodes = {
        str(node["id"]): node
        for node in _tree_nodes(_context_page(client, tree["parent"]))
    }

    supplier_child = nodes[str(tree["supplier"])]
    assert supplier_child["other_organisation"] is True
    assert supplier_child["tooltip"]["Organisation"] == "Test Supplier Account"
    assert not any(node_id.startswith("hidden") for node_id in nodes)


def test_properties_page_keeps_an_unreadable_parent(db, client, tree, as_supplier_user):
    """The properties page does not show the parent, but keeps it selected, so editing other fields keeps it."""
    response = client.get(url_for("AssetCrudUI:properties", id=tree["supplier"]))
    assert response.status_code == 200
    assert b"Prosumer secret site" not in response.data
    assert re.search(
        rf'<option value="{tree["parent"]}" selected>\s*\(another organisation\)</option>'.encode(),
        response.data,
    )

    child = db.session.get(GenericAsset, tree["supplier"])
    form_input = mock_asset_data_as_form_input(
        dict(
            id=child.id,
            name="Renamed supplier child",
            generic_asset_type_id=child.generic_asset_type_id,
            account_id=child.account_id,
            latitude=None,
            longitude=None,
            external_id=None,
        )
    )
    form_input["latitude"] = ""
    form_input["longitude"] = ""
    form_input["parent_asset_id"] = tree["parent"]
    response = client.post(
        url_for("AssetCrudUI:post", id=child.id), follow_redirects=True, data=form_input
    )
    assert b"Editing was successful" in response.data
    db.session.expire_all()
    child = db.session.get(GenericAsset, tree["supplier"])
    assert child.name == "Renamed supplier child"
    assert child.parent_asset_id == tree["parent"]
