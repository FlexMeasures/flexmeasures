# SPDX-License-Identifier: Apache-2.0

import pytest
from flask import url_for

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
@pytest.mark.parametrize("sort_key", ["sort_by", "sort-by"])
def test_search_and_sort_by_asset_type(
    client,
    setup_api_fresh_test_data,
    setup_accounts_fresh_db,
    requesting_user,
    fresh_db,
    sort_key,
):
    """Search and sort types for private and public assets, including ties."""
    battery = GenericAssetType(name="zzpilot-battery")
    solar = GenericAssetType(name="zzpilot-solar")
    account = setup_accounts_fresh_db["Prosumer"]
    private_battery = GenericAsset(
        name="zzunit alpha", generic_asset_type=battery, owner=account
    )
    public_battery = GenericAsset(name="zzunit beta", generic_asset_type=battery)
    private_solar = GenericAsset(
        name="zzunit gamma", generic_asset_type=solar, owner=account
    )
    fresh_db.session.add_all([private_battery, public_battery, private_solar])
    fresh_db.session.commit()
    battery_ids = sorted([private_battery.id, public_battery.id])
    solar_id = private_solar.id

    for filter_value in (None, "zzpilot zzunit"):
        query = {"all_accessible": True, sort_key: "asset_type", "sort_dir": "asc"}
        if filter_value is not None:
            query["filter"] = filter_value
        response = client.get(url_for("AssetAPI:index"), query_string=query)
        assert response.status_code == 200
        actual = [
            asset["id"]
            for asset in response.json
            if asset["id"] in battery_ids + [solar_id]
        ]
        assert actual == battery_ids + [solar_id]
        query["sort_dir"] = "desc"
        response = client.get(url_for("AssetAPI:index"), query_string=query)
        assert response.status_code == 200
        actual = [
            asset["id"]
            for asset in response.json
            if asset["id"] in battery_ids + [solar_id]
        ]
        assert actual == [solar_id] + battery_ids

    paged_ids = []
    for page in (1, 2, 3):
        response = client.get(
            url_for("AssetAPI:index"),
            query_string={
                "all_accessible": True,
                "filter": "zzpilot",
                sort_key: "asset_type",
                "sort_dir": "asc",
                "page": page,
                "per_page": 1,
            },
        )
        assert response.status_code == 200
        assert response.json["filtered-records"] == 3
        paged_ids.extend(asset["id"] for asset in response.json["data"])
    assert paged_ids == battery_ids + [solar_id]

    response = client.get(
        url_for("AssetAPI:index"),
        query_string={"all_accessible": True, "filter": "zzpilot-battery"},
    )
    assert response.status_code == 200
    assert sorted(asset["id"] for asset in response.json) == battery_ids


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_asset_type_search_does_not_leak_other_accounts(
    client,
    setup_api_fresh_test_data,
    setup_accounts_fresh_db,
    requesting_user,
    fresh_db,
):
    """A non-admin user searching by asset type only sees own-account and public assets."""
    wind = GenericAssetType(name="zzpilot-wind")
    own = GenericAsset(
        name="zzown wind",
        generic_asset_type=wind,
        owner=setup_accounts_fresh_db["Prosumer"],
    )
    other = GenericAsset(
        name="zzother wind",
        generic_asset_type=wind,
        owner=setup_accounts_fresh_db["Supplier"],
    )
    public = GenericAsset(name="zzpublic wind", generic_asset_type=wind)
    fresh_db.session.add_all([own, other, public])
    fresh_db.session.commit()
    own_id, other_id, public_id = own.id, other.id, public.id

    response = client.get(
        url_for("AssetAPI:index"),
        query_string={
            "all_accessible": True,
            "filter": "zzpilot-wind",
            "sort_by": "asset_type",
            "sort_dir": "asc",
        },
    )
    assert response.status_code == 200
    ids = {asset["id"] for asset in response.json}
    assert own_id in ids
    assert public_id in ids
    assert other_id not in ids


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_asset_type_search_and_sort_under_root_with_depth(
    client,
    setup_api_fresh_test_data,
    setup_accounts_fresh_db,
    requesting_user,
    fresh_db,
):
    """Type search and sorting respect the ``root`` and ``depth`` parameters."""
    site_type = GenericAssetType(name="zzpilot-site")
    battery = GenericAssetType(name="zzpilot-battery2")
    solar = GenericAssetType(name="zzpilot-solar2")
    account = setup_accounts_fresh_db["Prosumer"]
    site = GenericAsset(name="zzsite", generic_asset_type=site_type, owner=account)
    child_solar = GenericAsset(
        name="zzchild a", generic_asset_type=solar, owner=account, parent_asset=site
    )
    child_battery = GenericAsset(
        name="zzchild b", generic_asset_type=battery, owner=account, parent_asset=site
    )
    grandchild = GenericAsset(
        name="zzgrandchild",
        generic_asset_type=battery,
        owner=account,
        parent_asset=child_solar,
    )
    outside = GenericAsset(name="zzoutside", generic_asset_type=battery, owner=account)
    fresh_db.session.add_all([site, child_solar, child_battery, grandchild, outside])
    fresh_db.session.commit()
    site_id = site.id
    solar_id, battery_id, grandchild_id = (
        child_solar.id,
        child_battery.id,
        grandchild.id,
    )
    outside_id = outside.id

    def ids(**params):
        response = client.get(
            url_for("AssetAPI:index"),
            query_string={"root": site_id, "filter": "zzpilot-", **params},
        )
        assert response.status_code == 200
        return [asset["id"] for asset in response.json]

    # sorted by type name: battery2 < site < solar2; ties by id
    expected = sorted([battery_id, grandchild_id]) + [site_id, solar_id]
    assert ids(sort_by="asset_type", sort_dir="asc") == expected
    assert outside_id not in ids(sort_by="asset_type")
    # depth=1 drops the grandchild, depth=0 leaves only the root
    assert grandchild_id not in ids(depth=1, sort_by="asset_type")
    assert ids(depth=0, sort_by="asset_type") == [site_id]
    # filtering by type only
    assert ids(filter="zzpilot-solar2") == [solar_id]
