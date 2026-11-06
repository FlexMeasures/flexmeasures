from __future__ import annotations

from . import belief_charts, defaults  # noqa F401
from .chart_types import (
    SENSOR_CHART_TYPES,
    SensorChartType,
    UnknownChartType,
    get_sensor_chart_type,
)

# Every chart type that chart_type_to_chart_specs builds: the registry of sensor chart types (see chart_types.py),
# which plugins can add to.
# Asset charts are built through the registry of asset chart types instead.
CHART_TYPES: dict[str, SensorChartType] = SENSOR_CHART_TYPES

__all__ = [
    "CHART_TYPES",
    "SENSOR_CHART_TYPES",
    "UnknownChartType",
    "chart_type_to_chart_specs",
]


def chart_type_to_chart_specs(chart_type: str, **kwargs) -> dict:
    """Create chart specs of a given chart type, using FlexMeasures defaults for settings like width and height.

    Only the chart types in the registry of sensor chart types (CHART_TYPES) are built,
    so a request cannot reach other functions or data in the chart modules.

    :param chart_type:  Name of a chart type in CHART_TYPES, or its legacy name (e.g. "bar_chart" for "bar-chart").
    :returns:           A dictionary containing a vega-lite chart specification
    :raises UnknownChartType: if the chart type is not in CHART_TYPES.
    """
    return get_sensor_chart_type(chart_type).chart_specs(**kwargs)
