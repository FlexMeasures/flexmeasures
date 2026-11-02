"""The registry of asset chart types: the one place that lists the charts an asset can be drawn as.

Each chart type has a public, kebab-case name, which API users pass as ``chart-type``.
It also says which assets it applies to, which graphs it draws (its layout), and which function builds its Vega-Lite specs.

A layout is a list of graphs, each a dictionary in the format of a validated ``sensors_to_show`` entry:
a ``title`` and a list of ``plots`` holding the graph's sensors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from flexmeasures.data.models.charts.belief_charts import (
    CHARGE_POINT_COMPANION_TITLES,
    CHARGE_POINT_POWER_SENSOR_NAME,
    CHARGE_POINT_SESSIONS_TITLE,
    POWER_FLOW_BY_TYPE_TITLE,
    charge_point_session_sensors,
    charge_point_companion_graph,
    chart_for_chargepoint_sessions,
    chart_for_multiple_sensors,
)
from flexmeasures.data.models.charts.defaults import apply_chart_defaults

# The asset type of the charge points whose sessions the Charge Points chart shows.
CHARGE_POINT_ASSET_TYPE_NAME = "smartbuilding.chargepoint"


class UnknownAssetChartType(ValueError):
    """Raised for a name that is not in the registry of asset chart types."""


@dataclass(frozen=True)
class AssetChartType:
    """A chart an asset can be drawn as.

    :param name: the public, kebab-case name, as API users pass it in ``chart-type``.
    :param label: the name shown in the UI.
    :param description: what the chart shows, for the API documentation.
    :param applies_to: whether the chart type is meant for this asset.
    :param layout: the graphs the chart draws, given the asset's validated ``sensors_to_show``.
    :param builder: the function that builds the chart's Vega-Lite specs from the asset's validated ``sensors_to_show``.
    :param legacy_name: the name of the builder, which the chart endpoint took before the chart types had public names.
    """

    name: str
    label: str
    description: str
    applies_to: Callable[["GenericAsset"], bool]  # noqa F821
    layout: Callable[[list[dict]], list[dict]]
    builder: Callable[..., dict]
    legacy_name: str | None = None

    def chart_specs(self, **kwargs) -> dict:
        """Build the chart's Vega-Lite specs, with the FlexMeasures defaults for settings like width and height."""
        return apply_chart_defaults(self.builder)(**kwargs)

    def sensors(self, sensors_to_show: list[dict]) -> list["Sensor"]:  # noqa F821
        """The sensors whose data the chart draws, in the order of its layout.

        :param sensors_to_show: the asset's validated sensors_to_show.
        :returns: a unique list of sensors.
        """
        from flexmeasures.data.schemas.generic_assets import SensorsToShowSchema

        return SensorsToShowSchema.flatten(self.layout(sensors_to_show))


def _as_graph(entry: dict) -> dict:
    """The entry in the layout format, i.e. with its sensors in plots.

    Validated entries have that format already,
    except those suggested for an asset without sensors_to_show, which hold a top-level sensor or sensors.
    """
    if "plots" in entry:
        return entry
    graph = {
        key: value for key, value in entry.items() if key not in ("sensor", "sensors")
    }
    plots = []
    if "sensor" in entry:
        plots.append({"sensor": entry["sensor"]})
    if "sensors" in entry:
        plots.append({"sensors": entry["sensors"]})
    return {**graph, "plots": plots}


def default_layout(sensors_to_show: list[dict]) -> list[dict]:
    """A graph per entry in the asset's sensors_to_show, except the graph of charging-session timestamps.

    Those timestamps are not plottable quantities, so only the Charge Points chart draws them.
    """
    return [
        _as_graph(entry)
        for entry in sensors_to_show
        if entry.get("title") != CHARGE_POINT_SESSIONS_TITLE
    ]


def charge_point_sessions_layout(sensors_to_show: list[dict]) -> list[dict]:
    """The charging sessions, followed by the graphs drawn below them.

    The sessions graph holds the charging-session timestamps found in any graph.
    Below it come the Prices graph and, of the Power flow by type graph, the charge points power (see charge_point_companion_graph).
    """
    sensors_to_show = [_as_graph(entry) for entry in sensors_to_show]
    sessions_graph = {
        "title": CHARGE_POINT_SESSIONS_TITLE,
        "plots": [{"sensors": charge_point_session_sensors(sensors_to_show)}],
    }
    companion_graphs = [
        graph
        for entry in sensors_to_show
        if (graph := charge_point_companion_graph(entry)) is not None
    ]
    return [sessions_graph, *companion_graphs]


# The names that the layout of the Charge Points chart goes by, for the fast chart in the browser (handed to it by includes/graphs.html).
# The fast chart still lays out the graphs itself, by these names, so that it draws what charge_point_sessions_layout holds.
CHARGE_POINT_CHART_NAMES = {
    "sessionsTitle": CHARGE_POINT_SESSIONS_TITLE,
    "companionTitles": list(CHARGE_POINT_COMPANION_TITLES),
    "powerFlowTitle": POWER_FLOW_BY_TYPE_TITLE,
    "powerSensorName": CHARGE_POINT_POWER_SENSOR_NAME,
}


def has_charge_points(asset: "GenericAsset") -> bool:  # noqa F821
    """Whether the asset has a charge point among its children, as the asset page checks before offering the Charge Points chart."""
    return any(
        child.generic_asset_type.name == CHARGE_POINT_ASSET_TYPE_NAME
        for child in asset.child_assets
    )


DEFAULT_ASSET_CHART_TYPE = "default"

ASSET_CHART_TYPES: dict[str, AssetChartType] = {
    chart_type.name: chart_type
    for chart_type in (
        AssetChartType(
            name=DEFAULT_ASSET_CHART_TYPE,
            label="Default",
            description="a graph for each entry in the asset's sensors_to_show, except the charging sessions, which only 'charge-point-sessions' draws",
            applies_to=lambda asset: True,
            layout=default_layout,
            builder=chart_for_multiple_sensors,
            legacy_name="chart_for_multiple_sensors",
        ),
        AssetChartType(
            name="charge-point-sessions",
            label="Charge Points",
            description="the charging sessions of the asset's charge points, with its prices and charge points power below them",
            applies_to=has_charge_points,
            layout=charge_point_sessions_layout,
            builder=chart_for_chargepoint_sessions,
            legacy_name="chart_for_chargepoint_sessions",
        ),
    )
}

# The names the chart endpoint took before the chart types had public names, mapped to those public names.
LEGACY_ASSET_CHART_TYPE_NAMES: dict[str, str] = {
    chart_type.legacy_name: chart_type.name
    for chart_type in ASSET_CHART_TYPES.values()
    if chart_type.legacy_name
}


def get_asset_chart_type(name: str, accept_legacy_name: bool = True) -> AssetChartType:
    """Look up an asset chart type by its name.

    :param name: the public name of the chart type, or (if accepted) its legacy name.
    :param accept_legacy_name: whether to also accept the name of the chart type's builder.
    :returns: the chart type.
    :raises UnknownAssetChartType: if no chart type goes by that name.
    """
    if accept_legacy_name:
        name = LEGACY_ASSET_CHART_TYPE_NAMES.get(name, name)
    try:
        return ASSET_CHART_TYPES[name]
    except KeyError:
        message = f"Unknown asset chart type '{name}'; choose from {', '.join(ASSET_CHART_TYPES)}"
        if accept_legacy_name:
            message += (
                f" (or the deprecated {', '.join(LEGACY_ASSET_CHART_TYPE_NAMES)})"
            )
        raise UnknownAssetChartType(message + ".") from None
