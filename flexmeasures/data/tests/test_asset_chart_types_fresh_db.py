"""Tests for the asset chart types: what each one draws (issue #2795)."""

from __future__ import annotations

import pytest

from flexmeasures import Sensor
from flexmeasures.data.models.charts.belief_charts import (
    chart_for_chargepoint_sessions,
)
from flexmeasures.data.models.charts.chart_types import (
    ASSET_CHART_TYPES,
    UnknownAssetChartType,
    get_asset_chart_type,
)
from flexmeasures.utils.flexmeasures_inflection import capitalize


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


def _retitle(fresh_db, site, titles: dict[str, str]):
    """Rename graphs in the site's sensors_to_show."""
    site.sensors_to_show = [
        {**entry, "title": titles.get(entry["title"], entry["title"])}
        for entry in site.sensors_to_show
    ]
    fresh_db.session.commit()


@pytest.mark.parametrize(
    "prices_title, power_flow_title",
    [
        ("Prices", "Power flow by type"),
        ("prices", "Power flow by type"),
        ("Prices", "power flow by type"),
        ("prices", "power flow by type"),
    ],
)
def test_charge_points_chart_draws_its_companion_graphs_whatever_the_title_case(
    fresh_db, charge_hub_fresh_db: dict[str, Sensor], prices_title, power_flow_title
):
    """The Charge Points chart capitalizes graph titles, so a lowercase companion title still counts, and is restricted the same way."""
    site = charge_hub_fresh_db["arrival"].generic_asset
    _retitle(
        fresh_db, site, {"Prices": prices_title, "Power flow by type": power_flow_title}
    )

    chart_specs = site.chart(chart_type="charge-point-sessions")

    assert [graph["title"] for graph in chart_specs["vconcat"]] == [
        "Charge Point sessions",
        "Power flow by type",
        "Prices",
    ]
    # Of the power flows, only the charge points power is drawn.
    assert _sensor_ids_drawn(chart_specs) == {
        charge_hub_fresh_db[name].id
        for name in (
            "arrival",
            "departure",
            "plug in",
            "charge points power",
            "consumption price",
        )
    }


def test_charge_points_chart_leaves_the_sensors_to_show_it_is_given_alone(
    charge_hub_fresh_db: dict[str, Sensor],
):
    site = charge_hub_fresh_db["arrival"].generic_asset
    sensors_to_show = site.validate_sensors_to_show()
    # As GenericAsset.chart does before calling a chart builder.
    for sensor in charge_hub_fresh_db.values():
        sensor.sensor_type = sensor.name
    before = [
        [plot.get("sensors", plot.get("sensor")) for plot in entry["plots"]]
        for entry in sensors_to_show
    ]

    chart_for_chargepoint_sessions(sensors_to_show)

    assert [
        [plot.get("sensors", plot.get("sensor")) for plot in entry["plots"]]
        for entry in sensors_to_show
    ] == before


@pytest.mark.parametrize(
    "chart_type, titles",
    [
        ("default", {}),
        ("default", {"Prices": "prices", "Weather": "weather"}),
        ("charge-point-sessions", {}),
        (
            "charge-point-sessions",
            {"Prices": "prices", "Power flow by type": "power flow by type"},
        ),
    ],
)
def test_each_chart_type_draws_the_graphs_and_sensors_of_its_layout(
    fresh_db, charge_hub_fresh_db: dict[str, Sensor], chart_type, titles
):
    """The registry's layout of a chart type is what its Vega-Lite chart draws, graph by graph."""
    site = charge_hub_fresh_db["arrival"].generic_asset
    _retitle(fresh_db, site, titles)
    registered = get_asset_chart_type(chart_type)
    layout = registered.layout(site.validate_sensors_to_show())

    chart_specs = site.chart(chart_type=chart_type)

    assert [graph["title"] for graph in chart_specs["vconcat"]] == [
        capitalize(graph["title"]) for graph in layout
    ]
    for graph, drawn in zip(layout, chart_specs["vconcat"]):
        assert _sensor_ids_drawn(drawn) == {
            sensor.id for sensor in registered.sensors([graph])
        }, graph["title"]


@pytest.mark.parametrize(
    "chart_type, expected_names",
    [
        (
            "default",
            [
                "charge points power",
                "building power",
                "consumption price",
                "temperature",
                # Also in a graph of its own, which the default chart draws.
                "departure",
            ],
        ),
        (
            "charge-point-sessions",
            [
                # In the order of the graphs they are found in.
                "departure",
                "arrival",
                "plug in",
                "charge points power",
                "consumption price",
            ],
        ),
    ],
)
def test_chart_type_sensors(
    charge_hub_fresh_db: dict[str, Sensor], chart_type, expected_names
):
    site = charge_hub_fresh_db["arrival"].generic_asset
    sensors = get_asset_chart_type(chart_type).sensors(site.validate_sensors_to_show())
    assert [sensor.name for sensor in sensors] == expected_names


@pytest.mark.parametrize(
    "legacy_name, name",
    [
        ("chart_for_multiple_sensors", "default"),
        ("chart_for_chargepoint_sessions", "charge-point-sessions"),
    ],
)
def test_a_legacy_chart_type_name_draws_the_same_chart(
    charge_hub_fresh_db: dict[str, Sensor], legacy_name, name
):
    site = charge_hub_fresh_db["arrival"].generic_asset
    assert site.chart(chart_type=legacy_name) == site.chart(chart_type=name)


def test_without_a_chart_type_an_asset_gets_the_default_chart(
    charge_hub_fresh_db: dict[str, Sensor],
):
    site = charge_hub_fresh_db["arrival"].generic_asset
    assert site.chart() == site.chart(chart_type="default")


def test_an_unknown_chart_type_is_refused(charge_hub_fresh_db: dict[str, Sensor]):
    site = charge_hub_fresh_db["arrival"].generic_asset
    with pytest.raises(UnknownAssetChartType, match="charge-point-sessions"):
        site.chart(chart_type="bar_chart")


def test_the_charge_points_chart_applies_to_assets_with_a_charge_point(
    charge_hub_fresh_db: dict[str, Sensor],
):
    site = charge_hub_fresh_db["arrival"].generic_asset
    (charge_point,) = site.child_assets
    assert [
        name
        for name, chart_type in ASSET_CHART_TYPES.items()
        if chart_type.applies_to(site)
    ] == ["default", "charge-point-sessions"]
    assert [
        name
        for name, chart_type in ASSET_CHART_TYPES.items()
        if chart_type.applies_to(charge_point)
    ] == ["default"]


def test_a_companion_graph_left_without_sensors_is_not_in_the_layout(
    fresh_db, charge_hub_fresh_db: dict[str, Sensor]
):
    """Of a Power flow by type graph without the charge points power, nothing is drawn, so the layout leaves it out."""
    site = charge_hub_fresh_db["arrival"].generic_asset
    site.sensors_to_show = [
        (
            {**entry, "sensors": [charge_hub_fresh_db["building power"].id]}
            if entry["title"] == "Power flow by type"
            else entry
        )
        for entry in site.sensors_to_show
    ]
    fresh_db.session.commit()
    layout = get_asset_chart_type("charge-point-sessions").layout(
        site.validate_sensors_to_show()
    )

    chart_specs = site.chart(chart_type="charge-point-sessions")

    assert [graph["title"] for graph in layout] == [
        graph["title"] for graph in chart_specs["vconcat"]
    ]
    assert [graph["title"] for graph in layout] == ["Charge Point sessions", "Prices"]
