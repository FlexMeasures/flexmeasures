from __future__ import annotations

from typing import Callable

from . import belief_charts
from .defaults import apply_chart_defaults

# The chart types of a sensor chart, by the name a request gives them.
# The generic heatmap helper is left out: it is how daily_heatmap and weekly_heatmap are built.
SENSOR_CHART_TYPES: dict[str, Callable[..., dict]] = {
    "bar_chart": belief_charts.bar_chart,
    "histogram": belief_charts.histogram,
    "daily_heatmap": belief_charts.daily_heatmap,
    "weekly_heatmap": belief_charts.weekly_heatmap,
}

# The chart builders of an asset chart, by the name a request gives them.
ASSET_CHART_BUILDERS: dict[str, Callable[..., dict]] = {
    "chart_for_multiple_sensors": belief_charts.chart_for_multiple_sensors,
    "chart_for_chargepoint_sessions": belief_charts.chart_for_chargepoint_sessions,
}

# Every chart type that chart_type_to_chart_specs builds.
CHART_TYPES: dict[str, Callable[..., dict]] = {
    **SENSOR_CHART_TYPES,
    **ASSET_CHART_BUILDERS,
}


class UnknownChartType(ValueError):
    """Raised for a chart type that is not among the CHART_TYPES."""


def chart_type_to_chart_specs(chart_type: str, **kwargs) -> dict:
    """Create chart specs of a given chart type, using FlexMeasures defaults for settings like width and height.

    Only the chart types listed in CHART_TYPES are built,
    so a request cannot reach other functions or data in the chart modules.

    :param chart_type:  Name of a chart type in CHART_TYPES.
    :returns:           A dictionary containing a vega-lite chart specification
    :raises UnknownChartType: if the chart type is not in CHART_TYPES.
    """
    try:
        chart_builder = CHART_TYPES[chart_type]
    except KeyError:
        raise UnknownChartType(
            f"Unknown chart type '{chart_type}'; choose from {', '.join(CHART_TYPES)}."
        ) from None
    return apply_chart_defaults(chart_builder)(**kwargs)
