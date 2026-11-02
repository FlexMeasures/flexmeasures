"""Tests for the chart-type of an asset chart: the registry's names, the legacy names, and unknown names (issue #2795)."""

from __future__ import annotations

import json

import pytest
from flask import url_for

from flexmeasures import Sensor


def _get_chart(client, site, query: dict):
    return client.get(url_for("AssetAPI:get_chart", id=site.id), query_string=query)


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
# The asset page's Vega-Lite chart still sends the snake_case alias.
@pytest.mark.parametrize("parameter", ["chart-type", "chart_type"])
@pytest.mark.parametrize(
    "legacy_name, name",
    [
        ("chart_for_multiple_sensors", "default"),
        ("chart_for_chargepoint_sessions", "charge-point-sessions"),
    ],
)
def test_chart_accepts_the_new_and_the_legacy_chart_type_names(
    client,
    setup_roles_users_fresh_db,
    charge_hub_fresh_db: dict[str, Sensor],
    requesting_user,
    parameter,
    legacy_name,
    name,
):
    site = charge_hub_fresh_db["arrival"].generic_asset
    response = _get_chart(client, site, {parameter: name})
    legacy_response = _get_chart(client, site, {parameter: legacy_name})
    assert response.status_code == 200, response.data
    assert legacy_response.status_code == 200, legacy_response.data
    chart_specs = json.loads(response.data)
    assert json.loads(legacy_response.data) == chart_specs
    # The two chart types draw different charts, so the comparison above means something.
    assert (
        "Charge Point sessions" in [graph["title"] for graph in chart_specs["vconcat"]]
    ) == (name == "charge-point-sessions")


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_chart_draws_the_default_chart_without_a_chart_type(
    client,
    setup_roles_users_fresh_db,
    charge_hub_fresh_db: dict[str, Sensor],
    requesting_user,
):
    site = charge_hub_fresh_db["arrival"].generic_asset
    response = _get_chart(client, site, {})
    assert response.status_code == 200, response.data
    assert (
        json.loads(response.data)
        == json.loads(_get_chart(client, site, {"chart-type": "default"}).data)
        != json.loads(
            _get_chart(client, site, {"chart-type": "charge-point-sessions"}).data
        )
    )


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
@pytest.mark.parametrize(
    "chart_type",
    ["bar_chart", "daily_heatmap", "chart_for_chargepoint_session", "Default", ""],
)
def test_chart_refuses_an_unknown_chart_type(
    client,
    setup_roles_users_fresh_db,
    charge_hub_fresh_db: dict[str, Sensor],
    requesting_user,
    chart_type,
):
    site = charge_hub_fresh_db["arrival"].generic_asset
    response = _get_chart(client, site, {"chart-type": chart_type})
    assert response.status_code == 422, response.data
    assert "default, charge-point-sessions" in response.get_data(as_text=True)
