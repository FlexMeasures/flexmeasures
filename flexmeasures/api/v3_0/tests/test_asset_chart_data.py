"""Tests for which sensors an asset's chart data holds, per chart type (issue #2789).

The default chart leaves the graph of charging-session timestamps to the Charge Points chart,
so loading those sensors for it only fetches data that is thrown away.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
import pytz
from flask import url_for

from flexmeasures import Sensor
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import TimedBelief

START = datetime(2015, 1, 1, tzinfo=pytz.utc)


@pytest.fixture(scope="module")
def charge_hub(db) -> dict[str, Sensor]:
    """A public site whose dashboard has the graphs a site with charge points gets.

    One belief per sensor, so the chart data shows which sensors were loaded.
    The departure sensor is also in a graph of its own,
    to check that the default chart keeps a session sensor it draws elsewhere.
    """
    site_type = GenericAssetType(name="test_site_type_for_chart_sensors")
    db.session.add(site_type)
    site = GenericAsset(
        name="Test charge hub (chart sensors)", generic_asset_type=site_type
    )
    db.session.add(site)
    db.session.flush()

    units = {
        "charge points power": "kW",
        "building power": "kW",
        "consumption price": "EUR/MWh",
        "temperature": "°C",
        "arrival": "s",
        "departure": "s",
        "plug in": "s",
    }
    sensors = {
        name: Sensor(
            name=name,
            unit=unit,
            event_resolution=timedelta(minutes=15),
            generic_asset=site,
        )
        for name, unit in units.items()
    }
    db.session.add_all(sensors.values())
    db.session.flush()

    site.sensors_to_show = [
        {
            "title": "Power flow by type",
            "sensors": [
                sensors["charge points power"].id,
                sensors["building power"].id,
            ],
        },
        {"title": "Prices", "sensors": [sensors["consumption price"].id]},
        {"title": "Weather", "sensors": [sensors["temperature"].id]},
        {"title": "Departures", "sensors": [sensors["departure"].id]},
        {
            "title": "Charge Point sessions",
            "sensors": [
                sensors["arrival"].id,
                sensors["departure"].id,
                sensors["plug in"].id,
            ],
        },
    ]

    source = DataSource(name="test script", type="demo script")
    db.session.add(source)
    db.session.flush()
    for sensor in sensors.values():
        db.session.add(
            TimedBelief(
                sensor=sensor,
                event_start=START,
                event_value=1.0,
                belief_horizon=timedelta(0),
                source=source,
            )
        )
    db.session.commit()
    return sensors


def _names(sensors: list[Sensor]) -> list[str]:
    return [sensor.name for sensor in sensors]


def test_without_a_chart_type_all_sensors_are_loaded(charge_hub):
    site = charge_hub["arrival"].generic_asset
    assert _names(site.chart_sensors()) == [
        "charge points power",
        "building power",
        "consumption price",
        "temperature",
        "departure",
        "arrival",
        "plug in",
    ]


def test_default_chart_skips_the_charge_point_sessions_graph(charge_hub):
    site = charge_hub["arrival"].generic_asset
    assert _names(site.chart_sensors("chart_for_multiple_sensors")) == [
        "charge points power",
        "building power",
        "consumption price",
        "temperature",
        # Also in a graph of its own, which the default chart draws.
        "departure",
    ]


def test_charge_points_chart_loads_its_sessions_and_two_companion_graphs(
    charge_hub,
):
    site = charge_hub["arrival"].generic_asset
    assert _names(site.chart_sensors("chart_for_chargepoint_sessions")) == [
        "departure",
        "arrival",
        "plug in",
        "charge points power",
        "consumption price",
    ]


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
@pytest.mark.parametrize(
    "chart_type, expected_names",
    [
        (
            None,
            {
                "charge points power",
                "building power",
                "consumption price",
                "temperature",
                "arrival",
                "departure",
                "plug in",
            },
        ),
        (
            "chart_for_multiple_sensors",
            {
                "charge points power",
                "building power",
                "consumption price",
                "temperature",
                "departure",
            },
        ),
        (
            "chart_for_chargepoint_sessions",
            {
                "charge points power",
                "consumption price",
                "arrival",
                "departure",
                "plug in",
            },
        ),
    ],
)
def test_chart_data_holds_only_what_the_chart_type_draws(
    client, setup_roles_users, charge_hub, requesting_user, chart_type, expected_names
):
    site = charge_hub["arrival"].generic_asset
    query = {
        "event_starts_after": START.isoformat(),
        "event_ends_before": (START + timedelta(hours=1)).isoformat(),
        "compress_json": "true",
    }
    if chart_type is not None:
        query["chart-type"] = chart_type
    response = client.get(
        url_for("AssetAPI:get_chart_data", id=site.id), query_string=query
    )
    assert response.status_code == 200, response.data
    # The endpoint sends the JSON as a string, so it is not parsed for us.
    loaded_ids = {record["sid"] for record in json.loads(response.data)["data"]}
    id_by_name = {name: sensor.id for name, sensor in charge_hub.items()}
    assert loaded_ids == {id_by_name[name] for name in expected_names}
