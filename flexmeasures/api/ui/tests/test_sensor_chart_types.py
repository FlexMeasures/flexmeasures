"""The chart types a chart request may name, and what a request can and cannot change."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from flexmeasures.data.models.charts import (
    CHART_TYPES,
    SENSOR_CHART_TYPES,
    UnknownChartType,
    chart_type_to_chart_specs,
    defaults,
)
from flexmeasures.data.models.time_series import Sensor

# Module-level chart specs, which building a chart must leave as they are.
MODULE_SPECS = ("FIELD_DEFINITIONS", "REPLAY_RULER", "LEGIBILITY_DEFAULTS")

# Names in the chart modules that are not chart types.
NOT_CHART_TYPES = [
    "REPLAY_RULER",
    "FIELD_DEFINITIONS",
    "capitalize",
    "create_bar_chart_or_histogram_specs",
    "determine_shared_unit",
    "",
]

WINDOW = {"start": "2021-05-02T00:00:00+02:00", "end": "2021-05-03T00:00:00+02:00"}


def _gas_sensor(db) -> Sensor:
    return db.session.execute(
        select(Sensor).filter_by(name="some gas sensor")
    ).scalar_one()


@pytest.fixture
def module_specs():
    """Snapshot the module-level chart specs, and put them back afterwards, so a failing test cannot affect other tests."""
    snapshot = {name: deepcopy(getattr(defaults, name)) for name in MODULE_SPECS}
    yield snapshot
    for name, value in snapshot.items():
        spec = getattr(defaults, name)
        spec.clear()
        spec.update(deepcopy(value))


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
@pytest.mark.parametrize("prefix", ["/api/ui", "/api/dev"])
@pytest.mark.parametrize("chart_type", NOT_CHART_TYPES)
def test_sensor_chart_refuses_what_is_not_a_chart_type(
    client, setup_api_test_data, requesting_user, db, module_specs, prefix, chart_type
):
    sensor = _gas_sensor(db)
    response = client.get(
        f"{prefix}/sensor/{sensor.id}/chart",
        query_string={**WINDOW, "chart-type": chart_type, "dataset_name": "other"},
    )
    assert response.status_code == 422, response.data
    for name in MODULE_SPECS:
        assert getattr(defaults, name) == module_specs[name], name


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
@pytest.mark.parametrize("chart_type", NOT_CHART_TYPES)
def test_asset_chart_refuses_what_is_not_a_chart_type(
    client, setup_api_test_data, requesting_user, db, module_specs, chart_type
):
    sensor = _gas_sensor(db)
    response = client.get(
        f"/api/v3_0/assets/{sensor.generic_asset_id}/chart",
        query_string={**WINDOW, "chart-type": chart_type, "dataset_name": "other"},
    )
    assert response.status_code == 422, response.data
    for name in MODULE_SPECS:
        assert getattr(defaults, name) == module_specs[name], name


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
@pytest.mark.parametrize("chart_type", list(SENSOR_CHART_TYPES))
def test_a_sensor_chart_is_the_same_after_a_request_naming_something_else(
    client, setup_api_test_data, requesting_user, db, module_specs, chart_type
):
    sensor = _gas_sensor(db)
    url = f"/api/ui/sensor/{sensor.id}/chart"
    query = {**WINDOW, "chart-type": chart_type, "dataset_name": f"sensor_{sensor.id}"}

    before = client.get(url, query_string=query)
    for other in NOT_CHART_TYPES:
        client.get(
            url, query_string={**WINDOW, "chart-type": other, "dataset_name": "other"}
        )
    after = client.get(url, query_string=query)

    assert before.status_code == after.status_code == 200, after.data
    assert json.loads(after.data) == json.loads(before.data)


def test_building_a_chart_leaves_the_module_level_specs_alone(db, module_specs):
    """Every chart type's specs are built on copies of the module-level specs they use."""
    sensor = _gas_sensor(db)
    sensor.sensor_type = sensor.name
    for chart_type in SENSOR_CHART_TYPES:
        chart_type_to_chart_specs(
            chart_type, sensor=sensor, dataset_name="sensor", include_annotations=True
        )
    for name in MODULE_SPECS:
        assert getattr(defaults, name) == module_specs[name], name


@pytest.mark.parametrize("chart_type", NOT_CHART_TYPES)
def test_chart_type_to_chart_specs_builds_only_chart_types(chart_type):
    with pytest.raises(UnknownChartType):
        chart_type_to_chart_specs(chart_type, dataset_name="other")


def test_the_chart_types():
    assert list(SENSOR_CHART_TYPES) == [
        "bar_chart",
        "histogram",
        "daily_heatmap",
        "weekly_heatmap",
        "heatmap",
    ]
    assert set(CHART_TYPES) == set(SENSOR_CHART_TYPES) | {
        "chart_for_multiple_sensors",
        "chart_for_chargepoint_sessions",
    }


def test_chart_defaults_are_applied_to_a_copy_of_the_specs(module_specs):
    """Even a chart builder that hands back a module-level spec itself does not get it changed."""
    defaults.apply_chart_defaults(lambda: defaults.REPLAY_RULER)(
        dataset_name="other", include_annotations=True
    )
    assert defaults.REPLAY_RULER == module_specs["REPLAY_RULER"]
