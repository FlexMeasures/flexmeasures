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
from flexmeasures.data.models.charts.chart_types import LEGACY_SENSOR_CHART_TYPE_NAMES
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
    "heatmap",
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
@pytest.mark.parametrize("prefix", ["/api/ui", "/api/dev"])
def test_the_session_keeps_only_a_validated_chart_type(
    client, setup_api_test_data, requesting_user, db, prefix
):
    """A request sending both spellings is validated on the canonical one, so only that one may reach the session."""
    sensor = _gas_sensor(db)
    url = f"{prefix}/sensor/{sensor.id}/chart"
    response = client.get(
        url,
        query_string={
            **WINDOW,
            "chart-type": "bar_chart",
            "chart_type": "REPLAY_RULER",
        },
    )
    assert response.status_code == 200, response.data
    with client.session_transaction() as session:
        # The legacy name is stored as the public name it stands for.
        assert session["chart_type"] == "bar-chart"

    # The sensor page and its own chart request keep working.
    page = client.get(f"/sensors/{sensor.id}")
    assert page.status_code == 200
    assert "let chartType = 'bar-chart';" in page.data.decode()
    response = client.get(url, query_string={**WINDOW, "chart_type": "bar_chart"})
    assert response.status_code == 200, response.data


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


@pytest.mark.parametrize("heatmap", ["daily-heatmap", "weekly-heatmap"])
def test_a_heatmap_leaves_the_legend_of_later_charts_alone(
    setup_api_test_data, db, module_specs, heatmap
):
    """A heatmap without annotations sets its own legend position, which must not become the default for later charts."""
    sensor = _gas_sensor(db)
    sensor.sensor_type = sensor.name
    chart_type_to_chart_specs(
        heatmap, sensor=sensor, dataset_name="sensor", include_annotations=False
    )
    bar_chart = chart_type_to_chart_specs(
        "bar-chart", sensor=sensor, dataset_name="sensor", include_annotations=False
    )
    assert bar_chart["config"]["legend"]["orient"] == "bottom"
    assert defaults.LEGIBILITY_DEFAULTS == module_specs["LEGIBILITY_DEFAULTS"]


@pytest.mark.parametrize("chart_type", NOT_CHART_TYPES)
def test_chart_type_to_chart_specs_builds_only_chart_types(chart_type):
    with pytest.raises(UnknownChartType):
        chart_type_to_chart_specs(chart_type, dataset_name="other")


def test_the_chart_types():
    assert list(SENSOR_CHART_TYPES) == [
        "bar-chart",
        "histogram",
        "daily-heatmap",
        "weekly-heatmap",
    ]
    assert CHART_TYPES is SENSOR_CHART_TYPES


def test_chart_defaults_are_applied_to_a_copy_of_the_specs(module_specs):
    """Even a chart builder that hands back a module-level spec itself does not get it changed."""
    defaults.apply_chart_defaults(lambda: defaults.REPLAY_RULER)(
        dataset_name="other", include_annotations=True
    )
    assert defaults.REPLAY_RULER == module_specs["REPLAY_RULER"]


def test_the_api_docs_name_the_public_asset_chart_types_only():
    """The asset chart's chart-type lists the public chart type names, and mentions the legacy names only as deprecated."""
    from importlib.resources import files

    specs = json.loads(
        files("flexmeasures.ui").joinpath("static/openapi-specs.json").read_text()
    )
    parameters = specs["paths"]["/api/v3_0/assets/{id}/chart"]["get"]["parameters"]
    (chart_type,) = [p for p in parameters if p["name"] == "chart-type"]
    assert chart_type["schema"]["enum"] == ["default", "charge-point-sessions"]
    legacy_names = ("chart_for_multiple_sensors", "chart_for_chargepoint_sessions")
    for name in legacy_names:
        assert name not in json.dumps(chart_type["schema"])
    for sentence in chart_type["description"].split(". "):
        if any(name in sentence for name in legacy_names):
            assert "deprecated" in sentence, sentence


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
@pytest.mark.parametrize(
    "chart_type, public_name",
    [
        *[
            (name, name)
            for name in ("bar-chart", "histogram", "daily-heatmap", "weekly-heatmap")
        ],
        *LEGACY_SENSOR_CHART_TYPE_NAMES.items(),
    ],
)
def test_sensor_chart_accepts_the_public_and_the_legacy_chart_type_names(
    client, setup_api_test_data, requesting_user, db, chart_type, public_name
):
    """A legacy name draws the same chart as its public name, which is what the session keeps."""
    sensor = _gas_sensor(db)
    url = f"/api/ui/sensor/{sensor.id}/chart"
    query = {**WINDOW, "dataset_name": f"sensor_{sensor.id}"}

    response = client.get(url, query_string={**query, "chart-type": chart_type})
    assert response.status_code == 200, response.data
    with client.session_transaction() as session:
        assert session["chart_type"] == public_name

    public = client.get(url, query_string={**query, "chart-type": public_name})
    assert json.loads(response.data) == json.loads(public.data)


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
@pytest.mark.parametrize("chart_type", ["default", "charge-point-sessions"])
def test_sensor_chart_refuses_an_asset_chart_type(
    client, setup_api_test_data, requesting_user, db, chart_type
):
    sensor = _gas_sensor(db)
    response = client.get(
        f"/api/ui/sensor/{sensor.id}/chart",
        query_string={**WINDOW, "chart-type": chart_type},
    )
    assert response.status_code == 422, response.data


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
@pytest.mark.parametrize(
    "chart_type", ["test-plugin-sensor-chart", "test_plugin_sensor_chart"]
)
def test_sensor_chart_accepts_a_chart_type_registered_by_a_plugin(
    client,
    setup_api_test_data,
    requesting_user,
    db,
    plugin_sensor_chart_type,
    chart_type,
):
    """A chart type a plugin registers after the app was created is drawn, and the session keeps its public name."""
    sensor = _gas_sensor(db)
    url = f"/api/ui/sensor/{sensor.id}/chart"
    query = {**WINDOW, "dataset_name": f"sensor_{sensor.id}"}

    response = client.get(url, query_string={**query, "chart-type": chart_type})

    assert response.status_code == 200, response.data
    with client.session_transaction() as session:
        assert session["chart_type"] == "test-plugin-sensor-chart"
    # The test plugin's chart type draws a bar chart.
    bar_chart = client.get(url, query_string={**query, "chart-type": "bar-chart"})
    assert json.loads(response.data) == json.loads(bar_chart.data)


def test_chart_type_to_chart_specs_builds_a_chart_type_registered_by_a_plugin(
    setup_api_test_data, db, plugin_sensor_chart_type
):
    sensor = _gas_sensor(db)
    sensor.sensor_type = sensor.name
    kwargs = dict(sensor=sensor, dataset_name="sensor", include_annotations=False)
    assert chart_type_to_chart_specs(
        "test-plugin-sensor-chart", **kwargs
    ) == chart_type_to_chart_specs("bar-chart", **kwargs)
