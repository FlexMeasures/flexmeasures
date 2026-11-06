"""Tests for the chart picker on an asset's graphs page, which lists the chart types from the registry of asset chart types (issue #2795)."""

from __future__ import annotations

import re

import pytest
from flask import url_for

from flexmeasures import Sensor
from flexmeasures.data.models.charts.chart_types import LEGACY_ASSET_CHART_TYPE_NAMES
from flexmeasures.ui.tests.utils import login, logout


def _picker(client, asset) -> tuple[str, list[tuple[str, str]], str]:
    """The picker's display style, its (chart type, label) options, and the whole page."""
    page = client.get(url_for("AssetCrudUI:graphs", id=asset.id), follow_redirects=True)
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    (style,) = re.findall(
        r'<div id="chart-type-picker"[^>]*style="display: (\w+)"', html
    )
    options = re.findall(r'data-chart-type="([^"]+)">\s*<span>([^<]+)</span>', html)
    return style, options, html


@pytest.fixture
def as_prosumer_user_fresh_db(client, setup_roles_users_fresh_db):
    login(client, "test_prosumer_user@seita.nl", "testtest")
    yield
    logout(client)


def test_the_picker_offers_the_charge_points_chart_on_a_site_with_charge_points(
    client, charge_hub_fresh_db: dict[str, Sensor], as_prosumer_user_fresh_db
):
    site = charge_hub_fresh_db["arrival"].generic_asset

    style, options, html = _picker(client, site)

    assert style == "block"
    assert options == [
        ("default", "Default"),
        ("charge-point-sessions", "Charge Points"),
    ]
    # The page asks for the charts by their public names only.
    for legacy_name in LEGACY_ASSET_CHART_TYPE_NAMES:
        assert legacy_name not in html


def test_the_picker_stays_hidden_on_an_asset_without_charge_points(
    client, charge_hub_fresh_db: dict[str, Sensor], as_prosumer_user_fresh_db
):
    (charge_point,) = charge_hub_fresh_db["arrival"].generic_asset.child_assets

    style, options, _ = _picker(client, charge_point)

    assert style == "none"
    assert options == [("default", "Default")]


def test_the_picker_offers_a_chart_type_registered_by_a_plugin_where_it_applies(
    client,
    charge_hub_fresh_db: dict[str, Sensor],
    plugin_asset_chart_type,
    as_prosumer_user_fresh_db,
):
    site = charge_hub_fresh_db["arrival"].generic_asset
    (charge_point,) = site.child_assets

    _, site_options, _ = _picker(client, site)
    _, charge_point_options, _ = _picker(client, charge_point)

    assert site_options == [
        ("default", "Default"),
        ("charge-point-sessions", "Charge Points"),
        ("test-plugin-chart", "Test plugin chart"),
    ]
    # The test plugin's chart type applies to assets with charge points only.
    assert charge_point_options == [("default", "Default")]
