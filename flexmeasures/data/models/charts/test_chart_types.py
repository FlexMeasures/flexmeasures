"""Tests for the registry of asset chart types (issue #2795)."""

import pytest

from flexmeasures.data.models.charts.chart_types import (
    ASSET_CHART_TYPES,
    DEFAULT_ASSET_CHART_TYPE,
    LEGACY_ASSET_CHART_TYPE_NAMES,
    UnknownAssetChartType,
    get_asset_chart_type,
)


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
    with pytest.raises(UnknownAssetChartType, match="default, charge-point-sessions"):
        get_asset_chart_type("daily_heatmap")
