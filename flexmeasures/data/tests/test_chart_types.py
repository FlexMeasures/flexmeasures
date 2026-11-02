"""Tests for the registry of asset chart types (issue #2795)."""

import pytest
from marshmallow import ValidationError, validate

from flexmeasures.data.models.charts.chart_types import (
    ASSET_CHART_TYPES,
    DEFAULT_ASSET_CHART_TYPE,
    LEGACY_ASSET_CHART_TYPE_NAMES,
    AssetChartType,
    UnknownAssetChartType,
    get_asset_chart_type,
    register_asset_chart_type,
)
from flexmeasures.data.schemas.charts import AssetChartTypeField

# A field made at import, like those of the API schemas, before plugins register their chart types.
FIELD_MADE_BEFORE_PLUGINS_REGISTER = AssetChartTypeField(accept_legacy_names=True)


def test_the_registry_lists_the_asset_chart_types():
    assert list(ASSET_CHART_TYPES) == ["default", "charge-point-sessions"]
    assert DEFAULT_ASSET_CHART_TYPE == "default"
    for name, chart_type in ASSET_CHART_TYPES.items():
        assert chart_type.name == name


def test_the_legacy_names_are_the_names_of_the_chart_builders():
    assert LEGACY_ASSET_CHART_TYPE_NAMES == {
        "chart_for_multiple_sensors": "default",
        "chart_for_chargepoint_sessions": "charge-point-sessions",
    }
    for legacy_name, name in LEGACY_ASSET_CHART_TYPE_NAMES.items():
        assert ASSET_CHART_TYPES[name].builder.__name__ == legacy_name


def test_looking_up_a_chart_type():
    assert get_asset_chart_type("charge-point-sessions").name == "charge-point-sessions"
    assert (
        get_asset_chart_type("chart_for_chargepoint_sessions").name
        == "charge-point-sessions"
    )
    with pytest.raises(UnknownAssetChartType):
        get_asset_chart_type("chart_for_chargepoint_sessions", accept_legacy_name=False)
    with pytest.raises(
        UnknownAssetChartType,
        match="default, charge-point-sessions \\(or the deprecated",
    ):
        get_asset_chart_type("daily_heatmap")
    with pytest.raises(
        UnknownAssetChartType, match="default, charge-point-sessions\\.$"
    ):
        get_asset_chart_type("daily_heatmap", accept_legacy_name=False)


def test_a_chart_type_field_checks_the_registry_before_its_own_validators():
    field = AssetChartTypeField(
        accept_legacy_names=True,
        validate=validate.NoneOf(["charge-point-sessions"]),
    )
    assert field.deserialize("default") == "default"
    assert field.deserialize("chart_for_multiple_sensors") == "default"
    with pytest.raises(ValidationError, match="Must be one of"):
        field.deserialize("bar_chart")
    # The extra validator sees the mapped name.
    with pytest.raises(ValidationError, match="Invalid input"):
        field.deserialize("chart_for_chargepoint_sessions")


def test_a_chart_type_registered_by_a_plugin_is_looked_up_and_accepted_by_the_field(
    plugin_asset_chart_type,
):
    field = FIELD_MADE_BEFORE_PLUGINS_REGISTER
    assert get_asset_chart_type("test-plugin-chart") is plugin_asset_chart_type
    assert field.deserialize("test-plugin-chart") == "test-plugin-chart"
    assert field.deserialize("test_plugin_chart") == "test-plugin-chart"
    with pytest.raises(
        ValidationError,
        match="Must be one of: default, charge-point-sessions, test-plugin-chart\\.",
    ):
        field.deserialize("bar_chart")


@pytest.mark.parametrize(
    "name, legacy_name",
    [
        ("charge-point-sessions", None),
        ("chart_for_chargepoint_sessions", None),
        ("test-plugin-chart-2", "default"),
        ("test-plugin-chart-2", "chart_for_multiple_sensors"),
        ("test-plugin-chart-2", "test-plugin-chart-2"),
    ],
)
def test_registering_a_chart_type_refuses_a_name_already_taken(name, legacy_name):
    chart_type = ASSET_CHART_TYPES["default"]
    registry = dict(ASSET_CHART_TYPES)
    legacy_names = dict(LEGACY_ASSET_CHART_TYPE_NAMES)
    with pytest.raises(ValueError, match="Cannot register asset chart type"):
        register_asset_chart_type(
            AssetChartType(
                name=name,
                label="Taken",
                description="a chart type whose name is taken",
                applies_to=chart_type.applies_to,
                layout=chart_type.layout,
                builder=chart_type.builder,
                legacy_name=legacy_name,
            )
        )
    # Nothing was registered.
    assert ASSET_CHART_TYPES == registry
    assert LEGACY_ASSET_CHART_TYPE_NAMES == legacy_names
