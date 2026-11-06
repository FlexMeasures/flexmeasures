"""The registries of chart types: the one place that lists the charts an asset or a sensor can be drawn as.

Each chart type has a public, kebab-case name, which API users pass as ``chart-type``.
It also says which assets or sensors it applies to, and which function builds its Vega-Lite specs.
An asset chart type also says which graphs it draws (its layout).

A layout is a list of graphs, each a dictionary in the format of a validated ``sensors_to_show`` entry:
a ``title`` and a list of ``plots`` holding the graph's sensors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from flexmeasures.data.models.charts.belief_charts import (
    CHARGE_POINT_COMPANION_TITLES,
    CHARGE_POINT_POWER_SENSOR_NAME,
    CHARGE_POINT_SESSIONS_TITLE,
    POWER_FLOW_BY_TYPE_TITLE,
    bar_chart,
    charge_point_session_sensors,
    charge_point_companion_graph,
    chart_for_chargepoint_sessions,
    chart_for_multiple_sensors,
    daily_heatmap,
    histogram,
    weekly_heatmap,
)
from flexmeasures.data.models.charts.defaults import apply_chart_defaults

# The asset type of the charge points whose sessions the Charge Points chart shows.
CHARGE_POINT_ASSET_TYPE_NAME = "smartbuilding.chargepoint"


class UnknownChartType(ValueError):
    """Raised for a name that is not in a registry of chart types."""


class UnknownAssetChartType(UnknownChartType):
    """Raised for a name that is not in the registry of asset chart types."""


class UnknownSensorChartType(UnknownChartType):
    """Raised for a name that is not in the registry of sensor chart types."""


class ChartType:
    """What the asset and sensor chart types have in common: a public name, an optional legacy name, and a builder of Vega-Lite specs."""

    name: str
    legacy_name: str | None
    builder: Callable[..., dict]

    def chart_specs(self, **kwargs) -> dict:
        """Build the chart's Vega-Lite specs, with the FlexMeasures defaults for settings like width and height."""
        return apply_chart_defaults(self.builder)(**kwargs)


ChartTypeT = TypeVar("ChartTypeT", bound=ChartType)


class ChartTypeRegistry(Generic[ChartTypeT]):
    """The chart types of one kind (asset or sensor chart types), by their public names.

    It also maps the legacy names, which the chart endpoints took before the chart types had public names, to those public names.
    """

    def __init__(self, kind: str, unknown_error: type[UnknownChartType]):
        """Set up an empty registry.

        :param kind: what the chart types draw, as named in messages (e.g. "asset").
        :param unknown_error: the error to raise for a name that is not in the registry.
        """
        self.kind = kind
        self.unknown_error = unknown_error
        self.chart_types: dict[str, ChartTypeT] = {}
        self.legacy_names: dict[str, str] = {}

    def register(self, chart_type: ChartTypeT) -> ChartTypeT:
        """Add a chart type to the registry.

        :param chart_type: the chart type to register.
        :returns: the registered chart type.
        :raises ValueError: if its name or legacy name is already taken, as a name or legacy name of a registered chart type.
        """
        taken = set(self.chart_types) | set(self.legacy_names)
        for name in (chart_type.name, chart_type.legacy_name):
            if name in taken:
                raise ValueError(
                    f"Cannot register {self.kind} chart type '{chart_type.name}': the name '{name}' is already taken by a registered {self.kind} chart type."
                )
        if chart_type.name == chart_type.legacy_name:
            raise ValueError(
                f"Cannot register {self.kind} chart type '{chart_type.name}': its legacy name should differ from its name."
            )
        self.chart_types[chart_type.name] = chart_type
        if chart_type.legacy_name:
            self.legacy_names[chart_type.legacy_name] = chart_type.name
        return chart_type

    def public_name(self, name: str) -> str:
        """The public name for a legacy name; any other name is returned as it is."""
        return self.legacy_names.get(name, name)

    def get(self, name: str, accept_legacy_name: bool = True) -> ChartTypeT:
        """Look up a chart type by its name.

        :param name: the public name of the chart type, or (if accepted) its legacy name.
        :param accept_legacy_name: whether to also accept the legacy name.
        :returns: the chart type.
        :raises UnknownChartType: (in fact, the registry's unknown_error) if no chart type goes by that name.
        """
        if accept_legacy_name:
            name = self.public_name(name)
        try:
            return self.chart_types[name]
        except KeyError:
            message = f"Unknown {self.kind} chart type '{name}'; choose from {', '.join(self.chart_types)}"
            if accept_legacy_name and self.legacy_names:
                message += f" (or the deprecated {', '.join(self.legacy_names)})"
            raise self.unknown_error(message + ".") from None


@dataclass(frozen=True)
class AssetChartType(ChartType):
    """A chart an asset can be drawn as.

    Plugins can add their own, using register_asset_chart_type.
    These fields are provisional: they may still change before plugins can rely on them.

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

ASSET_CHART_TYPE_REGISTRY: ChartTypeRegistry[AssetChartType] = ChartTypeRegistry(
    "asset", UnknownAssetChartType
)

# The registry: the asset chart types by their public names.
ASSET_CHART_TYPES: dict[str, AssetChartType] = ASSET_CHART_TYPE_REGISTRY.chart_types

# The names the chart endpoint took before the chart types had public names, mapped to those public names.
LEGACY_ASSET_CHART_TYPE_NAMES: dict[str, str] = ASSET_CHART_TYPE_REGISTRY.legacy_names


def register_asset_chart_type(chart_type: AssetChartType) -> AssetChartType:
    """Add a chart type to the registry of asset chart types.

    Plugins call this when they are set up (e.g. in their ``__init__``),
    after which the chart API accepts the chart type's name and the asset page offers it on the assets it applies to.
    To avoid clashing with chart types FlexMeasures may add later,
    prefix the name with the plugin's name (e.g. ``"my-plugin-heat-pumps"``).

    :param chart_type: the chart type to register.
    :returns: the registered chart type.
    :raises ValueError: if its name or legacy name is already taken, as a name or legacy name of a registered chart type.
    """
    return ASSET_CHART_TYPE_REGISTRY.register(chart_type)


register_asset_chart_type(
    AssetChartType(
        name=DEFAULT_ASSET_CHART_TYPE,
        label="Default",
        description="a graph for each entry in the asset's sensors_to_show, except the charging sessions, which only 'charge-point-sessions' draws",
        applies_to=lambda asset: True,
        layout=default_layout,
        builder=chart_for_multiple_sensors,
        legacy_name="chart_for_multiple_sensors",
    )
)
register_asset_chart_type(
    AssetChartType(
        name="charge-point-sessions",
        label="Charge Points",
        description="the charging sessions of the asset's charge points, with its prices and charge points power below them",
        applies_to=has_charge_points,
        layout=charge_point_sessions_layout,
        builder=chart_for_chargepoint_sessions,
        legacy_name="chart_for_chargepoint_sessions",
    )
)


def get_asset_chart_type(name: str, accept_legacy_name: bool = True) -> AssetChartType:
    """Look up an asset chart type by its name.

    :param name: the public name of the chart type, or (if accepted) its legacy name.
    :param accept_legacy_name: whether to also accept the name of the chart type's builder.
    :returns: the chart type.
    :raises UnknownAssetChartType: if no chart type goes by that name.
    """
    return ASSET_CHART_TYPE_REGISTRY.get(name, accept_legacy_name=accept_legacy_name)


@dataclass(frozen=True)
class SensorChartType(ChartType):
    """A chart a sensor can be drawn as.

    Plugins can add their own, using register_sensor_chart_type.
    These fields are provisional: they may still change before plugins can rely on them.

    :param name: the public, kebab-case name, as the sensor chart endpoint takes it in ``chart-type``.
    :param label: the name shown in the UI.
    :param description: what the chart shows.
    :param applies_to: whether the chart type is meant for this sensor.
    :param builder: the function that builds the chart's Vega-Lite specs,
                    from the sensor, the window of events (``event_starts_after`` and ``event_ends_before``) and further chart settings.
    :param legacy_name: the name the chart endpoint took before the chart types had public names.
    """

    name: str
    label: str
    description: str
    applies_to: Callable[["Sensor"], bool]  # noqa F821
    builder: Callable[..., dict]
    legacy_name: str | None = None


DEFAULT_SENSOR_CHART_TYPE = "bar-chart"

SENSOR_CHART_TYPE_REGISTRY: ChartTypeRegistry[SensorChartType] = ChartTypeRegistry(
    "sensor", UnknownSensorChartType
)

# The registry: the sensor chart types by their public names.
SENSOR_CHART_TYPES: dict[str, SensorChartType] = SENSOR_CHART_TYPE_REGISTRY.chart_types

# The names the sensor chart endpoint took before the chart types had public names, mapped to those public names.
LEGACY_SENSOR_CHART_TYPE_NAMES: dict[str, str] = SENSOR_CHART_TYPE_REGISTRY.legacy_names


def register_sensor_chart_type(chart_type: SensorChartType) -> SensorChartType:
    """Add a chart type to the registry of sensor chart types.

    Plugins call this when they are set up (e.g. in their ``__init__``),
    after which the sensor chart endpoint accepts the chart type's name and the sensor page offers it on the sensors it applies to.
    To avoid clashing with chart types FlexMeasures may add later,
    prefix the name with the plugin's name (e.g. ``"my-plugin-duration-curve"``).

    :param chart_type: the chart type to register.
    :returns: the registered chart type.
    :raises ValueError: if its name or legacy name is already taken, as a name or legacy name of a registered chart type.
    """
    return SENSOR_CHART_TYPE_REGISTRY.register(chart_type)


def get_sensor_chart_type(
    name: str, accept_legacy_name: bool = True
) -> SensorChartType:
    """Look up a sensor chart type by its name.

    :param name: the public name of the chart type, or (if accepted) its legacy name.
    :param accept_legacy_name: whether to also accept the name the chart endpoint took before the chart types had public names.
    :returns: the chart type.
    :raises UnknownSensorChartType: if no chart type goes by that name.
    """
    return SENSOR_CHART_TYPE_REGISTRY.get(name, accept_legacy_name=accept_legacy_name)


def _applies_to_any_sensor(sensor: "Sensor") -> bool:  # noqa F821
    """Whether the chart type applies to the sensor, which the built-in sensor chart types all do."""
    return True


# The built-in sensor chart types, which the fast chart on the sensor page also draws (see fast-chart.js).
# The generic heatmap helper is left out: it is how the daily and weekly heatmaps are built.
register_sensor_chart_type(
    SensorChartType(
        name=DEFAULT_SENSOR_CHART_TYPE,
        label="Bar chart",
        description="the sensor's data over time, as bars",
        applies_to=_applies_to_any_sensor,
        builder=bar_chart,
        legacy_name="bar_chart",
    )
)
register_sensor_chart_type(
    SensorChartType(
        name="histogram",
        label="Histogram",
        description="how often the sensor's values fall in each bin",
        applies_to=_applies_to_any_sensor,
        builder=histogram,
    )
)
register_sensor_chart_type(
    SensorChartType(
        name="daily-heatmap",
        label="Daily heatmap",
        description="the sensor's data as a heatmap, with a row per day",
        applies_to=_applies_to_any_sensor,
        builder=daily_heatmap,
        legacy_name="daily_heatmap",
    )
)
register_sensor_chart_type(
    SensorChartType(
        name="weekly-heatmap",
        label="Weekly heatmap",
        description="the sensor's data as a heatmap, with a row per week",
        applies_to=_applies_to_any_sensor,
        builder=weekly_heatmap,
        legacy_name="weekly_heatmap",
    )
)
