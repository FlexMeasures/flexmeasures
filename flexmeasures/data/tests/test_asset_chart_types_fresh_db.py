"""Tests for the asset chart types: what each one draws (issue #2795)."""

from __future__ import annotations

import pytest

from flexmeasures import Sensor
from flexmeasures.data.models.charts.belief_charts import (
    chart_for_chargepoint_sessions,
)


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
    fresh_db, charge_hub: dict[str, Sensor], prices_title, power_flow_title
):
    """The Charge Points chart capitalizes graph titles, so a lowercase companion title still counts, and is restricted the same way."""
    site = charge_hub["arrival"].generic_asset
    _retitle(
        fresh_db, site, {"Prices": prices_title, "Power flow by type": power_flow_title}
    )

    chart_specs = site.chart(chart_type="chart_for_chargepoint_sessions")

    assert [graph["title"] for graph in chart_specs["vconcat"]] == [
        "Charge Point sessions",
        "Power flow by type",
        "Prices",
    ]
    # Of the power flows, only the charge points power is drawn.
    assert _sensor_ids_drawn(chart_specs) == {
        charge_hub[name].id
        for name in (
            "arrival",
            "departure",
            "plug in",
            "charge points power",
            "consumption price",
        )
    }


def test_charge_points_chart_leaves_the_sensors_to_show_it_is_given_alone(
    charge_hub: dict[str, Sensor],
):
    site = charge_hub["arrival"].generic_asset
    sensors_to_show = site.validate_sensors_to_show()
    # As GenericAsset.chart does before calling a chart builder.
    for sensor in charge_hub.values():
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
