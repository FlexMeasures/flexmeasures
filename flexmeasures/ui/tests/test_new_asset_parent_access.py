"""The new-asset page shows nothing about a parent asset the user may not see."""

import pytest
from flask import url_for
from sqlalchemy import select

from flexmeasures import Asset


@pytest.fixture
def foreign_and_own_parent(db, setup_accounts, setup_generic_asset_types):
    """Two parent assets (page requests commit the session, so later tests in this module find them already there)."""
    existing = {
        a.name: a
        for a in db.session.scalars(
            select(Asset).where(Asset.name.in_(["Supplier secret site", "Own site"]))
        )
    }
    if len(existing) == 2:
        return existing["Supplier secret site"], existing["Own site"]
    foreign = Asset(
        name="Supplier secret site",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Supplier"],
        latitude=12.345,
        longitude=67.891,
    )
    own = Asset(
        name="Own site",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Prosumer"],
        latitude=52.0,
        longitude=4.0,
    )
    db.session.add_all([foreign, own])
    db.session.flush()
    return foreign, own


def new_asset_page(client, **args):
    return client.get(url_for("AssetCrudUI:get", id="new", **args))


def test_new_asset_page_refuses_a_foreign_parent(
    client, setup_accounts, foreign_and_own_parent, as_prosumer_account_admin
):
    foreign, _ = foreign_and_own_parent
    for args in (
        dict(parent_asset_id=foreign.id),
        dict(parent_asset_id=foreign.id, account_id=setup_accounts["Prosumer"].id),
    ):
        response = new_asset_page(client, **args)
        assert response.status_code == 403
        page = response.get_data(as_text=True)
        assert "Supplier secret site" not in page
        assert "12.345" not in page
        assert f"({setup_accounts['Supplier'].id})" not in page


def test_new_asset_page_with_own_parent(
    client, setup_accounts, foreign_and_own_parent, as_prosumer_account_admin
):
    _, own = foreign_and_own_parent
    prosumer = setup_accounts["Prosumer"]
    for args in (
        dict(parent_asset_id=own.id),
        dict(parent_asset_id=own.id, account_id=prosumer.id),
    ):
        response = new_asset_page(client, **args)
        assert response.status_code == 200
        assert "Own site" in response.get_data(as_text=True)


def test_new_asset_page_with_unknown_parent(client, as_prosumer_account_admin):
    response = new_asset_page(client, parent_asset_id=999999)
    assert response.status_code == 404
