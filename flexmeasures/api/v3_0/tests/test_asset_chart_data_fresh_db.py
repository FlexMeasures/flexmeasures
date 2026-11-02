"""Tests for which sensors an asset's chart data holds, per chart type (issue #2789).

The default chart leaves the graph of charging-session timestamps to the Charge Points chart,
so loading those sensors for it only fetches data that is thrown away.
The charge_hub_fresh_db fixture (in flexmeasures/conftest.py) is a site with the graphs a site with charge points gets.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
import pytz
from flask import url_for

from flexmeasures import Sensor

# When the charge_hub_fresh_db fixture's beliefs are about.
START = datetime(2015, 1, 1, tzinfo=pytz.utc)


def _names(sensors: list[Sensor]) -> list[str]:
    return [sensor.name for sensor in sensors]


def test_without_a_chart_type_all_sensors_are_loaded(charge_hub_fresh_db):
    site = charge_hub_fresh_db["arrival"].generic_asset
    assert _names(site.chart_sensors()) == [
        "charge points power",
        "building power",
        "consumption price",
        "temperature",
        "departure",
        "arrival",
        "plug in",
    ]


def test_default_chart_skips_the_charge_point_sessions_graph(charge_hub_fresh_db):
    site = charge_hub_fresh_db["arrival"].generic_asset
    assert _names(site.chart_sensors("default")) == [
        "charge points power",
        "building power",
        "consumption price",
        "temperature",
        # Also in a graph of its own, which the default chart draws.
        "departure",
    ]


def test_charge_points_chart_loads_its_sessions_and_two_companion_graphs(
    charge_hub_fresh_db,
):
    site = charge_hub_fresh_db["arrival"].generic_asset
    assert _names(site.chart_sensors("charge-point-sessions")) == [
        "departure",
        "arrival",
        "plug in",
        "charge points power",
        "consumption price",
    ]


def _sensor_ids_drawn(chart_specs: dict | list) -> set[int]:
    """The ids of the sensors that the filters in these chart specs let through."""
    ids: set[int] = set()
    if isinstance(chart_specs, dict):
        sensor_filter = chart_specs.get("filter")
        if (
            isinstance(sensor_filter, dict)
            and sensor_filter.get("field") == "sensor.id"
        ):
            ids.update(sensor_filter["oneOf"])
        for value in chart_specs.values():
            ids |= _sensor_ids_drawn(value)
    elif isinstance(chart_specs, list):
        for value in chart_specs:
            ids |= _sensor_ids_drawn(value)
    return ids


@pytest.mark.parametrize(
    "prices_title, power_flow_title",
    [
        ("Prices", "Power flow by type"),
        ("prices", "Power flow by type"),
        ("Prices", "power flow by type"),
        ("prices", "power flow by type"),
    ],
)
def test_charge_points_chart_loads_what_it_draws_whatever_the_title_case(
    fresh_db, charge_hub_fresh_db, prices_title, power_flow_title
):
    """The Charge Points chart capitalizes graph titles, so a lowercase companion title still counts."""
    site = charge_hub_fresh_db["arrival"].generic_asset
    titles = {"Prices": prices_title, "Power flow by type": power_flow_title}
    site.sensors_to_show = [
        {**entry, "title": titles.get(entry["title"], entry["title"])}
        for entry in site.sensors_to_show
    ]
    fresh_db.session.commit()

    loaded = site.chart_sensors("charge-point-sessions")
    assert _names(loaded) == [
        "departure",
        "arrival",
        "plug in",
        "charge points power",
        "consumption price",
    ]
    chart_specs = site.chart(chart_type="charge-point-sessions")
    assert _sensor_ids_drawn(chart_specs) == {sensor.id for sensor in loaded}


ALL_SENSORS = {
    "charge points power",
    "building power",
    "consumption price",
    "temperature",
    "arrival",
    "departure",
    "plug in",
}
DEFAULT_CHART_SENSORS = {
    "charge points power",
    "building power",
    "consumption price",
    "temperature",
    "departure",
}
CHARGE_POINTS_CHART_SENSORS = {
    "charge points power",
    "consumption price",
    "arrival",
    "departure",
    "plug in",
}


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
# The same parameter name as the chart endpoint takes, including its snake_case alias.
@pytest.mark.parametrize("parameter", ["chart-type", "chart_type"])
@pytest.mark.parametrize(
    "chart_type, expected_names",
    [
        (None, ALL_SENSORS),
        # An empty value counts as none.
        ("", ALL_SENSORS),
        ("default", DEFAULT_CHART_SENSORS),
        ("charge-point-sessions", CHARGE_POINTS_CHART_SENSORS),
        # The legacy names, as the chart endpoint takes them.
        ("chart_for_multiple_sensors", DEFAULT_CHART_SENSORS),
        ("chart_for_chargepoint_sessions", CHARGE_POINTS_CHART_SENSORS),
    ],
)
def test_chart_data_holds_only_what_the_chart_type_draws(
    client,
    setup_roles_users_fresh_db,
    charge_hub_fresh_db,
    requesting_user,
    parameter,
    chart_type,
    expected_names,
):
    site = charge_hub_fresh_db["arrival"].generic_asset
    query = {
        "event_starts_after": START.isoformat(),
        "event_ends_before": (START + timedelta(hours=1)).isoformat(),
        "compress_json": "true",
    }
    if chart_type is not None:
        query[parameter] = chart_type
    response = client.get(
        url_for("AssetAPI:get_chart_data", id=site.id), query_string=query
    )
    assert response.status_code == 200, response.data
    # The endpoint sends the JSON as a string, so it is not parsed for us.
    loaded_ids = {record["sid"] for record in json.loads(response.data)["data"]}
    id_by_name = {name: sensor.id for name, sensor in charge_hub_fresh_db.items()}
    assert loaded_ids == {id_by_name[name] for name in expected_names}


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
@pytest.mark.parametrize(
    "chart_type",
    [
        "bar_chart",
        "Default",
        "chart_for_chargepoint_session",
    ],
)
def test_chart_data_refuses_an_unknown_chart_type(
    client,
    setup_roles_users_fresh_db,
    charge_hub_fresh_db,
    requesting_user,
    chart_type,
):
    site = charge_hub_fresh_db["arrival"].generic_asset
    response = client.get(
        url_for("AssetAPI:get_chart_data", id=site.id),
        query_string={
            "event_starts_after": START.isoformat(),
            "event_ends_before": (START + timedelta(hours=1)).isoformat(),
            "chart-type": chart_type,
        },
    )
    assert response.status_code == 422, response.data
    assert "default, charge-point-sessions" in response.get_data(as_text=True)
