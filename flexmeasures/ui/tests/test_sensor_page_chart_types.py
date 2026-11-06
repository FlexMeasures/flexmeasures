"""Tests for the chart picker on a sensor's page, which lists the chart types from the registry of sensor chart types (issue #2795)."""

from __future__ import annotations

import re

from flask import url_for

from flexmeasures.data.models.charts.chart_types import LEGACY_SENSOR_CHART_TYPE_NAMES
from flexmeasures.data.services.users import find_user_by_email

BUILT_IN_OPTIONS = [
    ("bar-chart", "Bar chart"),
    ("histogram", "Histogram"),
    ("daily-heatmap", "Daily heatmap"),
    ("weekly-heatmap", "Weekly heatmap"),
]


def _prosumer_sensors(db) -> dict:
    """The sensors of the first Prosumer asset, by name."""
    user = find_user_by_email("test_prosumer_user@seita.nl")
    sensors = {sensor.name: sensor for sensor in user.account.generic_assets[0].sensors}
    db.session.expunge(user)
    return sensors


def _sensor_page(client, sensor) -> tuple[list[tuple[str, str]], str, str]:
    """The picker's (chart type, label) options, the chart type the page starts with, and the whole page."""
    page = client.get(url_for("SensorUI:get", id=sensor.id), follow_redirects=True)
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    (picker,) = re.findall(r'<div id="chart-type-picker".*?</ul>', html, re.DOTALL)
    options = re.findall(r'data-chart-type="([^"]+)">([^<]+)</a>', picker)
    (chart_type,) = re.findall(r"let chartType = '([^']*)';", html)
    return options, chart_type, html


def test_the_picker_offers_the_built_in_chart_types_by_their_public_names(
    db, client, setup_assets, as_prosumer_user1
):
    sensor = _prosumer_sensors(db)["power"]

    options, chart_type, html = _sensor_page(client, sensor)

    assert options == BUILT_IN_OPTIONS
    assert chart_type == "bar-chart"
    # The page asks for the charts by their public names only.
    for legacy_name in LEGACY_SENSOR_CHART_TYPE_NAMES:
        assert f'"{legacy_name}"' not in html
        assert f"'{legacy_name}'" not in html


def test_the_picker_offers_a_chart_type_registered_by_a_plugin_where_it_applies(
    db, client, setup_assets, as_prosumer_user1, plugin_sensor_chart_type
):
    sensors = _prosumer_sensors(db)

    power_options, _, html = _sensor_page(client, sensors["power"])
    capacity_options, _, _ = _sensor_page(client, sensors["consumption-capacity"])

    assert power_options == [
        *BUILT_IN_OPTIONS,
        ("test-plugin-sensor-chart", "Test plugin sensor chart"),
    ]
    # The test plugin's chart type applies to sensors named "power" only.
    assert capacity_options == BUILT_IN_OPTIONS
    # The page asks the fast chart whether it draws the chart type, and shows the Vega-Lite chart for a chart type it does not draw (see test_fast_chart.py).
    assert "return fastChartDrawsChartType(chartType);" in html


def test_the_page_starts_with_the_chart_type_last_chosen(
    db, client, setup_assets, as_prosumer_user1, plugin_sensor_chart_type
):
    """The chart type in the session is used where it applies, by its public name also when the session holds a legacy name."""
    sensors = _prosumer_sensors(db)
    expectations = [
        # session value, sensor, chart type the page starts with
        ("daily_heatmap", "power", "daily-heatmap"),
        ("weekly-heatmap", "power", "weekly-heatmap"),
        ("test-plugin-sensor-chart", "power", "test-plugin-sensor-chart"),
        ("test-plugin-sensor-chart", "consumption-capacity", "bar-chart"),
        ("default", "power", "bar-chart"),
    ]
    for session_value, sensor_name, expected in expectations:
        with client.session_transaction() as session:
            session["chart_type"] = session_value
        _, chart_type, _ = _sensor_page(client, sensors[sensor_name])
        assert chart_type == expected, (session_value, sensor_name)
