from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

from flexmeasures.data.models.charts.defaults import FIELD_DEFINITIONS, REPLAY_RULER
from flexmeasures.utils.flexmeasures_inflection import (
    capitalize,
)
from flexmeasures.utils.coding_utils import flatten_unique
from flexmeasures.utils.unit_utils import find_smallest_common_unit, get_unit_dimension


def create_bar_chart_or_histogram_specs(
    sensor: "Sensor",  # noqa F821
    event_starts_after: datetime | None = None,
    event_ends_before: datetime | None = None,
    chart_type: str = "bar_chart",
    **override_chart_specs: dict,
):
    """
    This function generates the specifications required to visualize sensor data either as a bar chart or a histogram.
    The chart type (bar_chart or histogram) can be specified, and various field definitions are set up based on the sensor attributes and
    event time range. The resulting specifications can be customized further through additional keyword arguments.

    The function handles the following:
    - Determines unit and formats for the sensor data.
    - Configures event value and event start field definitions.
    - Sets the appropriate mark type and interpolation based on sensor attributes.
    - Defines chart specifications for both bar charts and histograms, including titles, axis configurations, and tooltips.
    - Merges any additional specifications provided through keyword arguments into the final chart specifications.
    """
    unit = sensor.unit if sensor.unit else "a.u."
    event_value_field_definition = dict(
        title=f"{capitalize(sensor.sensor_type)} ({unit})",
        format=[".3~r", unit],
        formatType="quantityWithUnitFormat",
        stack=None,
        **FIELD_DEFINITIONS["event_value"],
    )
    if unit == "%":
        event_value_field_definition["scale"] = dict(
            domain={"unionWith": [0, 105]}, nice=False
        )
    event_start_field_definition = FIELD_DEFINITIONS["event_start"].copy()
    event_start_field_definition["timeUnit"] = {
        "unit": "yearmonthdatehoursminutesseconds",
        "step": sensor.event_resolution.total_seconds(),
    }
    if event_starts_after and event_ends_before:
        event_start_field_definition["scale"] = {
            "domain": [
                event_starts_after.timestamp() * 10**3,
                event_ends_before.timestamp() * 10**3,
            ]
        }
    mark_type = "bar"
    mark_interpolate = None
    if sensor.event_resolution == timedelta(0) and sensor.has_attribute("interpolate"):
        mark_type = "area"
        mark_interpolate = sensor.get_attribute("interpolate")
    replay_ruler = REPLAY_RULER.copy()
    if chart_type == "histogram":
        description = "A histogram showing the distribution of sensor data."
        x = {
            **event_value_field_definition,
            "bin": True,
        }
        y = {
            "aggregate": "count",
            "title": "Count",
        }
        replay_ruler["encoding"] = {
            "detail": {
                "field": "belief_time",
                "type": "temporal",
                "title": None,
            },
        }
    else:
        description = (f"A simple {mark_type} chart showing sensor data.",)
        x = event_start_field_definition
        y = event_value_field_definition

    chart_specs = {
        "description": description,
        "title": capitalize(sensor.name) if sensor.name != sensor.sensor_type else None,
        "layer": [
            {
                "mark": {
                    "type": mark_type,
                    "interpolate": mark_interpolate,
                    "clip": True,
                    "width": {"band": 0.999},
                },
                "encoding": {
                    "x": x,
                    "y": y,
                    "color": FIELD_DEFINITIONS["source_name"],
                    "detail": FIELD_DEFINITIONS["source"],
                    "opacity": {"value": 0.7},
                    "tooltip": [
                        (
                            FIELD_DEFINITIONS["full_date"]
                            if chart_type != "histogram"
                            else None
                        ),
                        {
                            **event_value_field_definition,
                            **dict(title=f"{capitalize(sensor.sensor_type)}"),
                        },
                        FIELD_DEFINITIONS["source_name_and_id"],
                        FIELD_DEFINITIONS["source_model"],
                    ],
                },
                "transform": [
                    {
                        "calculate": "datum.source.name + ' (ID: ' + datum.source.id + ')'",
                        "as": "source_name_and_id",
                    },
                ],
                "selection": {
                    "scroll": {"type": "interval", "bind": "scales", "encodings": ["x"]}
                },
            },
            replay_ruler,
        ],
    }
    for k, v in override_chart_specs.items():
        chart_specs[k] = v
    return chart_specs


def histogram(
    sensor: "Sensor",  # noqa F821
    event_starts_after: datetime | None = None,
    event_ends_before: datetime | None = None,
    **override_chart_specs: dict,
):
    """
    Generates specifications for a histogram chart using sensor data. This function leverages
    the `create_bar_chart_or_histogram_specs` helper function, specifying `chart_type` as 'histogram'.
    """

    chart_type = "histogram"
    chart_specs = create_bar_chart_or_histogram_specs(
        sensor,
        event_starts_after,
        event_ends_before,
        chart_type,
        **override_chart_specs,
    )
    return chart_specs


def bar_chart(
    sensor: "Sensor",  # noqa F821
    event_starts_after: datetime | None = None,
    event_ends_before: datetime | None = None,
    **override_chart_specs: dict,
):
    """
    Generates specifications for a bar chart using sensor data. This function leverages
    the `create_bar_chart_or_histogram_specs` helper function to create the specifications.
    """

    chart_specs = create_bar_chart_or_histogram_specs(
        sensor,
        event_starts_after,
        event_ends_before,
        **override_chart_specs,
    )
    return chart_specs


def daily_heatmap(
    sensor: "Sensor",  # noqa F821
    event_starts_after: datetime | None = None,
    event_ends_before: datetime | None = None,
    **override_chart_specs: dict,
):
    return heatmap(
        sensor,
        event_starts_after,
        event_ends_before,
        split="daily",
        **override_chart_specs,
    )


def weekly_heatmap(
    sensor: "Sensor",  # noqa F821
    event_starts_after: datetime | None = None,
    event_ends_before: datetime | None = None,
    **override_chart_specs: dict,
):
    return heatmap(
        sensor,
        event_starts_after,
        event_ends_before,
        split="weekly",
        **override_chart_specs,
    )


def heatmap(
    sensor: "Sensor",  # noqa F821
    event_starts_after: datetime | None = None,
    event_ends_before: datetime | None = None,
    split: str = "weekly",
    **override_chart_specs: dict,
):
    unit = sensor.unit if sensor.unit else "a.u."

    if split == "daily":
        x_time_unit = "hoursminutesseconds"
        y_time_unit = "yearmonthdate"
        x_domain_max = 24
        x_axis_label_expression = "timeFormat(datum.value, '%H:%M')"
        x_axis_label_offset = None
        y_axis_label_offset_expression = (
            "(scale('y', 24 * 60 * 60 * 1000) - scale('y', 0)) / 2"
        )
        x_axis_tick_count = None
        y_axis_tick_count = "day"
        ruler_y_axis_label_offset_expression = (
            "(scale('y', 24 * 60 * 60 * 1000) - scale('y', 0))"
        )
        x_axis_label_bound = False
    elif split == "weekly":
        x_time_unit = "dayhoursminutesseconds"
        y_time_unit = "yearweek"
        x_domain_max = 7 * 24
        x_axis_tick_count = "day"
        y_axis_tick_count = "week"
        x_axis_label_expression = "timeFormat(datum.value, '%A')"
        x_axis_label_offset = {
            "expr": "(scale('x', 24 * 60 * 60 * 1000) - scale('x', 0)) / 2",
        }
        y_axis_label_offset_expression = (
            "(scale('y', 7 * 24 * 60 * 60 * 1000) - scale('y', 0)) / 2"
        )
        ruler_y_axis_label_offset_expression = (
            "(scale('y', 7 * 24 * 60 * 60 * 1000) - scale('y', 0))"
        )
        x_axis_label_bound = True
    else:
        raise NotImplementedError(f"Split '{split}' is not implemented.")
    event_value_field_definition = dict(
        title=f"{capitalize(sensor.sensor_type)} ({unit})",
        format=[".3~r", unit],
        formatType="quantityWithUnitFormat",
        stack=None,
        **FIELD_DEFINITIONS["event_value"],
        scale={"scheme": "blueorange", "domainMid": 0, "domain": {"unionWith": [0]}},
    )
    event_start_field_definition = dict(
        field="event_start",
        type="temporal",
        title=None,
        timeUnit={
            "unit": x_time_unit,
            "step": sensor.event_resolution.total_seconds(),
        },
        axis={
            "tickCount": x_axis_tick_count,
            "labelBound": x_axis_label_bound,
            "labelExpr": x_axis_label_expression,
            "labelFlush": False,
            "labelOffset": x_axis_label_offset,
            "labelOverlap": True,
            "labelSeparation": 1,
        },
        scale={
            "domain": [
                {"hours": 0},
                {"hours": x_domain_max},
            ]
        },
    )
    event_start_date_field_definition = dict(
        field="event_start",
        type="temporal",
        title=None,
        timeUnit={
            "unit": y_time_unit,
        },
        axis={
            "tickCount": y_axis_tick_count,
            # Center align the date labels
            "labelOffset": {
                "expr": y_axis_label_offset_expression,
            },
            "labelFlush": False,
            "labelBound": True,
        },
    )
    if event_starts_after and event_ends_before:
        event_start_date_field_definition["scale"] = {
            "domain": [
                event_starts_after.timestamp() * 10**3,
                event_ends_before.timestamp() * 10**3,
            ],
        }
    mark = {"type": "rect", "clip": True, "opacity": 0.7}
    tooltip = [
        FIELD_DEFINITIONS["full_date"],
        {
            **event_value_field_definition,
            **dict(title=f"{capitalize(sensor.sensor_type)}"),
        },
        FIELD_DEFINITIONS["source_name_and_id"],
        FIELD_DEFINITIONS["source_model"],
    ]
    chart_specs = {
        "description": f"A {split} heatmap showing sensor data.",
        # the sensor type is already shown as the y-axis title (avoid redundant info)
        "title": capitalize(sensor.name) if sensor.name != sensor.sensor_type else None,
        "layer": [
            {
                "mark": mark,
                "encoding": {
                    "x": event_start_field_definition,
                    "y": event_start_date_field_definition,
                    "color": event_value_field_definition,
                    "detail": FIELD_DEFINITIONS["source"],
                    "tooltip": tooltip,
                },
                "transform": [
                    {
                        # Mask overlapping data during the fall DST transition, which we show later with a special layer
                        "filter": "timezoneoffset(datum.event_start) >= timezoneoffset(datum.event_start + 60 * 60 * 1000) && timezoneoffset(datum.event_start) <= timezoneoffset(datum.event_start - 60 * 60 * 1000)"
                    },
                    {
                        "calculate": "datum.source.name + ' (ID: ' + datum.source.id + ')'",
                        "as": "source_name_and_id",
                    },
                    # In case of multiple sources, show the one with the most visible data
                    {
                        "joinaggregate": [{"op": "count", "as": "source_count"}],
                        "groupby": ["source.id"],
                    },
                    {
                        "window": [
                            {"op": "rank", "field": "source_count", "as": "source_rank"}
                        ],
                        "sort": [{"field": "source_count", "order": "descending"}],
                        "frame": [None, None],
                    },
                    {"filter": "datum.source_rank == 1"},
                    # In case of a tied rank, arbitrarily choose the first one occurring in the data
                    {
                        "window": [
                            {
                                "op": "first_value",
                                "field": "source.id",
                                "as": "first_source_id",
                            }
                        ],
                    },
                    {"filter": "datum.source.id == datum.first_source_id"},
                ],
            },
            {
                "data": {"name": "replay"},
                "mark": {
                    "type": "rule",
                },
                "encoding": {
                    "x": {
                        "field": "belief_time",
                        "type": "temporal",
                        "timeUnit": x_time_unit,
                    },
                    "y": {
                        "field": "belief_time",
                        "type": "temporal",
                        "timeUnit": y_time_unit,
                    },
                    "yOffset": {
                        "value": {
                            "expr": ruler_y_axis_label_offset_expression,
                        }
                    },
                },
            },
            create_fall_dst_transition_layer(
                sensor.timezone,
                mark,
                event_value_field_definition,
                event_start_field_definition,
                tooltip,
                split=split,
            ),
        ],
    }
    for k, v in override_chart_specs.items():
        chart_specs[k] = v
    chart_specs["config"] = {
        "legend": {"orient": "right"},
        # "legend": {"direction": "horizontal"},
    }
    return chart_specs


def create_fall_dst_transition_layer(
    timezone,
    mark,
    event_value_field_definition,
    event_start_field_definition,
    tooltip,
    split: str,
) -> dict:
    """Special layer for showing data during the daylight savings time transition in fall."""
    if split == "daily":
        step = 12
        calculate_second_bin = "timezoneoffset(datum.event_start + 60 * 60 * 1000) > timezoneoffset(datum.event_start) ? datum.event_start : datum.event_start + 12 * 60 * 60 * 1000"
        calculate_next_bin = (
            "datum.dst_transition_event_start + 12 * 60 * 60 * 1000 - 60 * 60 * 1000"
        )
    elif split == "weekly":
        step = 7 * 12
        calculate_second_bin = "timezoneoffset(datum.event_start + 60 * 60 * 1000) > timezoneoffset(datum.event_start) ? datum.event_start : datum.event_start + 7 * 12 * 60 * 60 * 1000"
        calculate_next_bin = "datum.dst_transition_event_start + 7 * 12 * 60 * 60 * 1000 - 60 * 60 * 1000"
    else:
        raise NotImplementedError(f"Split '{split}' is not implemented.")
    return {
        "mark": mark,
        "encoding": {
            "x": event_start_field_definition,
            "y": {
                "field": "dst_transition_event_start",
                "type": "temporal",
                "title": None,
                "timeUnit": {"unit": "yearmonthdatehours", "step": step},
            },
            "y2": {
                "field": "dst_transition_event_start_next",
                "timeUnit": {"unit": "yearmonthdatehours", "step": step},
            },
            "color": event_value_field_definition,
            "detail": FIELD_DEFINITIONS["source"],
            "tooltip": [
                {
                    "field": "event_start",
                    "type": "temporal",
                    "title": "Timezone",
                    "timeUnit": "utc",
                    "format": [timezone],
                    "formatType": "timezoneFormat",
                },
                *tooltip,
            ],
        },
        "transform": [
            {
                "filter": "timezoneoffset(datum.event_start) < timezoneoffset(datum.event_start + 60 * 60 * 1000) || timezoneoffset(datum.event_start) > timezoneoffset(datum.event_start - 60 * 60 * 1000)",
            },
            {
                # Push the more recent hour into the second 12-hour bin
                "calculate": calculate_second_bin,
                "as": "dst_transition_event_start",
            },
            {
                # Calculate a time point in the next 12-hour bin
                "calculate": calculate_next_bin,
                "as": "dst_transition_event_start_next",
            },
            {
                "calculate": "datum.source.name + ' (ID: ' + datum.source.id + ')'",
                "as": "source_name_and_id",
            },
        ],
    }


def chart_for_multiple_sensors(
    sensors_to_show: list["Sensor" | list["Sensor"] | dict[str, "Sensor"]],  # noqa F821
    event_starts_after: datetime | None = None,
    event_ends_before: datetime | None = None,
    combine_legend: bool = True,
    **override_chart_specs: dict,
):
    # Determine the shared data resolution
    all_shown_sensors = flatten_unique(sensors_to_show)
    condition = list(
        sensor.event_resolution
        for sensor in all_shown_sensors
        if sensor.event_resolution > timedelta(0)
    )
    minimum_non_zero_resolution = min(condition) if any(condition) else timedelta(0)

    # Set up field definition for event starts
    event_start_field_definition = FIELD_DEFINITIONS["event_start"].copy()
    event_start_field_definition["timeUnit"] = {
        "unit": "yearmonthdatehoursminutesseconds",
        "step": minimum_non_zero_resolution.total_seconds(),
    }
    # If a time window was set explicitly, adjust the domain to show the full window regardless of available data
    if event_starts_after and event_ends_before:
        event_start_field_definition["scale"] = {
            "domain": [
                event_starts_after.timestamp() * 10**3,
                event_ends_before.timestamp() * 10**3,
            ]
        }

    sensors_specs = []
    for entry in sensors_to_show:
        title = entry.get("title")
        if title == "Charge Point sessions":
            continue
        sensors = entry.get("sensors")
        # List the sensors that go into one row
        row_sensors: list["Sensor"] = sensors  # noqa F821

        # Set up field definition for sensor descriptions
        sensor_field_definition = FIELD_DEFINITIONS["sensor_description"].copy()
        sensor_field_definition["scale"] = dict(
            domain=[sensor.as_dict["description"] for sensor in row_sensors]
        )

        # Derive the unit that should be shown
        unit = determine_shared_unit(row_sensors)
        sensor_type = determine_shared_sensor_type(row_sensors)

        # Set up field definition for event values
        event_value_field_definition = dict(
            title=f"{capitalize(sensor_type)} ({unit})",
            format=[".3~r", unit],
            formatType="quantityWithUnitFormat",
            stack=None,
            **FIELD_DEFINITIONS["event_value"],
        )
        if unit == "%":
            event_value_field_definition["scale"] = dict(
                domain={"unionWith": [0, 105]}, nice=False
            )

        # Set up shared tooltip
        shared_tooltip = [
            dict(
                field="sensor.description",
                type="nominal",
                title="Sensor",
            ),
            {
                **event_value_field_definition,
                **dict(title=f"{capitalize(sensor_type)}"),
            },
            FIELD_DEFINITIONS["full_date"],
            dict(
                field="belief_horizon",
                type="quantitative",
                title="Horizon",
                format=["d", 4],
                formatType="timedeltaFormat",
            ),
            {
                **event_value_field_definition,
                **dict(title=f"{capitalize(sensor_type)}"),
            },
            FIELD_DEFINITIONS["source_name_and_id"],
            FIELD_DEFINITIONS["source_type"],
            FIELD_DEFINITIONS["source_model"],
        ]

        # Draw a line for each sensor (and each source)
        layers = [
            create_line_layer(
                row_sensors,
                event_start_field_definition,
                event_value_field_definition,
                sensor_field_definition,
                combine_legend=combine_legend,
            )
        ]

        # Optionally, draw transparent full-height rectangles that activate the tooltip anywhere in the graph
        # (to be precise, only at points on the x-axis where there is data)
        if len(row_sensors) == 1:
            # With multiple sensors, we cannot do this, because it is ambiguous which tooltip to activate (instead, we use a different brush in the circle layer)
            layers.append(
                create_rect_layer(
                    event_start_field_definition,
                    event_value_field_definition,
                    shared_tooltip,
                )
            )

        # Draw circle markers that are shown on hover
        layers.append(
            create_circle_layer(
                row_sensors,
                event_start_field_definition,
                event_value_field_definition,
                sensor_field_definition,
                shared_tooltip,
            )
        )
        layers.append(REPLAY_RULER)

        # Layer the lines, rectangles and circles within one row, and filter by which sensors are represented in the row
        sensor_specs = {
            "title": f"{capitalize(title)}" if title else None,
            "transform": [
                {
                    "filter": {
                        "field": "sensor.id",
                        "oneOf": [sensor.id for sensor in row_sensors],
                    }
                }
            ],
            "layer": layers,
            "width": "container",
        }
        sensors_specs.append(sensor_specs)

    # Vertically concatenate the rows
    chart_specs = dict(
        description="A vertically concatenated chart showing sensor data.",
        vconcat=[*sensors_specs],
        transform=[
            {
                "calculate": "datum.source.name + ' (ID: ' + datum.source.id + ')'",
                "as": "source_name_and_id",
            },
        ],
    )
    chart_specs["config"] = {
        "view": {"continuousWidth": 800, "continuousHeight": 150},
        "autosize": {"type": "fit-x", "contains": "padding"},
    }
    if combine_legend is True:
        chart_specs["resolve"] = {"scale": {"x": "shared"}}
    else:
        chart_specs["resolve"] = {"scale": {"color": "independent"}}
    for k, v in override_chart_specs.items():
        chart_specs[k] = v
    return chart_specs


def determine_shared_unit(sensors: list["Sensor"]) -> str:  # noqa F821
    units = list(set([sensor.unit for sensor in sensors if sensor.unit]))
    shared_unit, _ = find_smallest_common_unit(units)

    # Replace with 'dimensionless' in case of empty unit
    return shared_unit if shared_unit else "dimensionless"


def determine_shared_sensor_type(sensors: list["Sensor"]) -> str:  # noqa F821
    sensor_types = list(set([sensor.sensor_type for sensor in sensors]))

    # Return the sole sensor type
    if len(sensor_types) == 1:
        return sensor_types[0]

    # Check the units for common cases
    shared_unit = determine_shared_unit(sensors)
    return get_unit_dimension(shared_unit)


def create_line_layer(
    sensors: list["Sensor"],  # noqa F821
    event_start_field_definition: dict,
    event_value_field_definition: dict,
    sensor_field_definition: dict,
    combine_legend: bool,
):
    scale_values = False
    if len(sensors) > 1:
        shared_unit = determine_shared_unit(sensors)
        if shared_unit != "a.u.":
            scale_values = True

    # Use linear interpolation if any of the sensors shown within one row is instantaneous; otherwise, use step-after
    if any(sensor.event_resolution == timedelta(0) for sensor in sensors):
        interpolate = "linear"
    else:
        interpolate = "step-after"

    scaled_event_value_field_definition = event_value_field_definition.copy()
    scaled_event_value_field_definition["field"] = "scaled_event_value"

    line_layer = {
        "mark": {
            "type": "line",
            "interpolate": interpolate,
            "clip": True,
        },
        "encoding": {
            "x": event_start_field_definition,
            "y": scaled_event_value_field_definition,
            "color": (
                sensor_field_definition
                if combine_legend
                else {
                    **sensor_field_definition,
                    "legend": {
                        "orient": "right",
                        "columns": 1,
                        "direction": "vertical",
                    },
                }
            ),
            "strokeDash": {
                "scale": {
                    # Distinguish forecasters and schedulers by line stroke
                    "domain": ["forecaster", "scheduler", "other"],
                    # Schedulers get a dashed line, forecasters get a dotted line, the rest gets a solid line
                    "range": [[2, 2], [4, 4], [1, 0]],
                },
                "field": "source.type",
                "legend": {
                    "title": "Source",
                },
            },
            "detail": [FIELD_DEFINITIONS["source"]],
        },
        "selection": {
            "scroll": {"type": "interval", "bind": "scales", "encodings": ["x"]}
        },
        "transform": [
            {
                "calculate": (
                    "datum.event_value"
                    if not scale_values
                    else "datum.event_value * datum.scale_factor"
                ),
                "as": "scaled_event_value",
            }
        ],
    }
    return line_layer


def create_circle_layer(
    sensors: list["Sensor"],  # noqa F821
    event_start_field_definition: dict,
    event_value_field_definition: dict,
    sensor_field_definition: dict,
    shared_tooltip: list,
):
    scale_values = False
    if len(sensors) > 1:
        shared_unit = determine_shared_unit(sensors)
        if shared_unit != "a.u.":
            scale_values = True

    scaled_event_value_field_definition = event_value_field_definition.copy()
    scaled_event_value_field_definition["field"] = "scaled_event_value"
    scaled_shared_tooltip: list[dict] = deepcopy(
        shared_tooltip
    )  # deepcopy so the next line doesn't update the dicts
    scaled_shared_tooltip[1]["field"] = "scaled_event_value"
    params = [
        {
            "name": "hover_x_brush",
            "select": {
                "type": "point",
                "encodings": ["x"],
                "on": "mouseover",
                "nearest": False,
                "clear": "mouseout",
            },
        }
    ]
    if len(sensors) > 1:
        # extra brush for showing the tooltip of the closest sensor
        params.append(
            {
                "name": "hover_nearest_brush",
                "select": {
                    "type": "point",
                    "on": "mouseover",
                    "nearest": True,
                    "clear": "mouseout",
                },
            }
        )
    or_conditions = [{"param": "hover_x_brush", "empty": False}]
    if len(sensors) > 1:
        or_conditions.append({"param": "hover_nearest_brush", "empty": False})
    circle_layer = {
        "mark": {
            "type": "circle",
            "opacity": 1,
            "clip": True,
        },
        "encoding": {
            "x": event_start_field_definition,
            "y": scaled_event_value_field_definition,
            "color": sensor_field_definition,
            "size": {
                "condition": {"value": "200", "test": {"or": or_conditions}},
                "value": "0",
            },
            "tooltip": scaled_shared_tooltip,
        },
        "params": params,
        "transform": [
            {
                "calculate": (
                    "datum.event_value"
                    if not scale_values
                    else "datum.event_value * datum.scale_factor"
                ),
                "as": "scaled_event_value",
            }
        ],
    }
    return circle_layer


def create_rect_layer(
    event_start_field_definition: dict,
    event_value_field_definition: dict,
    shared_tooltip: list,
):
    rect_layer = {
        "mark": {
            "type": "rect",
            "y2": "height",
            "opacity": 0,
        },
        "encoding": {
            "x": event_start_field_definition,
            "y": {
                "condition": {
                    "test": "isNaN(datum['event_value'])",
                    **event_value_field_definition,
                },
                "value": 0,
            },
            "tooltip": shared_tooltip,
        },
    }
    return rect_layer


def chart_for_chargepoint_sessions(
    sensors_to_show,
    event_starts_after=None,
    event_ends_before=None,
    combine_legend=True,
    **override_chart_specs,
) -> dict:

    all_sensors = []
    sensors_to_show_copy = sensors_to_show.copy()
    for entry in sensors_to_show_copy:
        sensors = entry.get("sensors")
        all_sensors.extend(
            [
                s
                for s in sensors
                if s.unit == "s"
                and s.name
                in [
                    "arrival",
                    "departure",
                    "start charging",
                    "stop charging",
                    "plug in",
                    "plug out",
                ]
            ]
        )

    sensor_ids = [s.id for s in all_sensors]

    cp_chart = {
        "title": "Charge Point sessions",
        "width": "container",
        "height": 300,
        "selection": {
            "scroll": {"type": "interval", "bind": "scales", "encodings": ["x"]}
        },
        "transform": [
            {"filter": {"field": "sensor.id", "oneOf": sensor_ids}},
            {"calculate": "datum.sensor.name", "as": "sensor_name"},
            {"calculate": "datum.sensor.asset_id", "as": "asset_id"},
            {"calculate": "datum.sensor.asset_description", "as": "asset"},
        ],
        "layer": [
            # --- Dotted Line: Arrival to Departure ---
            {
                "transform": [
                    {
                        "calculate": "datum.asset_id + '_' + timeFormat(datum.event_start, '%Y-%m-%dT%H:%M:%S')",
                        "as": "session_id",
                    },
                    {
                        "filter": "datum.sensor_name == 'arrival' || datum.sensor_name == 'departure'"
                    },
                    {
                        "pivot": "sensor_name",
                        "value": "event_value",
                        "groupby": ["session_id", "asset", "asset_id"],
                    },
                    {"filter": {"selection": "arr_dep"}},
                ],
                "selection": {
                    "scroll": {
                        "type": "interval",
                        "bind": "scales",
                        "encodings": ["x"],
                    },
                    "arr_dep": {
                        "type": "multi",
                        "encodings": ["color"],
                        "fields": ["asset"],
                        "bind": "legend",
                        "toggle": "event.ctrlKey",
                    },
                },
                "mark": {
                    "type": "rule",
                    "strokeWidth": 1,
                    "strokeDash": [4, 4],
                },
                "encoding": {
                    "x": {
                        "field": "arrival",
                        "type": "temporal",
                        "scale": {
                            "domain": [
                                event_starts_after.timestamp() * 1000,
                                event_ends_before.timestamp() * 1000,
                            ]
                        },
                    },
                    "x2": {
                        "field": "departure",
                        "type": "temporal",
                        "title": None,
                        "scale": {
                            "domain": [
                                event_starts_after.timestamp() * 1000,
                                event_ends_before.timestamp() * 1000,
                            ]
                        },
                    },
                    "y": {
                        "field": "asset_id",
                        "type": "nominal",
                        "scale": {
                            "domain": {"selection": "arr_dep", "field": "asset_id"}
                        },
                        "title": "Sessions",
                        "axis": {"labels": False, "ticks": False, "domain": False},
                    },
                    "yOffset": {
                        "field": "session_id",
                        "type": "nominal",
                        "bandPosition": 0.5,
                        "scale": {
                            "domain": {"selection": "arr_dep", "field": "session_id"}
                        },
                    },
                    "color": {
                        "field": "asset",
                        "type": "nominal",
                        "legend": {
                            "orient": "right",
                            "columns": 1,
                            "direction": "vertical",
                            "labelLimit": 200,
                        },
                    },
                    "tooltip": [
                        {
                            "field": "arrival",
                            "type": "temporal",
                            "title": "Arrival",
                            "format": "%Y-%m-%d %H:%M:%S",
                        },
                        {
                            "field": "departure",
                            "type": "temporal",
                            "title": "Departure",
                            "format": "%Y-%m-%d %H:%M:%S",
                        },
                        {
                            "field": "asset_id",
                            "type": "nominal",
                            "title": "Asset ID",
                        },
                    ],
                },
            },
            # --- Solid Line: Plug-in to Plug-out ---
            {
                "transform": [
                    {
                        "calculate": "datum.asset_id + '_' + timeFormat(datum.event_start, '%Y-%m-%dT%H:%M:%S')",
                        "as": "session_id",
                    },
                    {
                        "filter": "datum.sensor_name == 'plug in' || datum.sensor_name == 'plug out'"
                    },
                    {
                        "pivot": "sensor_name",
                        "value": "event_value",
                        "groupby": [
                            "session_id",
                            "asset",
                            "asset_id",
                        ],
                    },
                    {"filter": {"selection": "plugin_plugout"}},
                ],
                "selection": {
                    "plugin_plugout": {
                        "type": "multi",
                        "encodings": ["color"],
                        "fields": ["asset"],
                        "bind": "legend",
                        "toggle": "event.ctrlKey",
                    }
                },
                "mark": {
                    "type": "rule",
                    "strokeWidth": 2,
                },
                "encoding": {
                    "x": {
                        "field": "plug in",
                        "type": "temporal",
                        "scale": {
                            "domain": [
                                event_starts_after.timestamp() * 1000,
                                event_ends_before.timestamp() * 1000,
                            ]
                        },
                    },
                    "x2": {
                        "field": "plug out",
                        "type": "temporal",
                        "scale": {
                            "domain": [
                                event_starts_after.timestamp() * 1000,
                                event_ends_before.timestamp() * 1000,
                            ]
                        },
                    },
                    "y": {
                        "field": "asset_id",
                        "type": "nominal",
                        "scale": {
                            "domain": {
                                "selection": "plugin_plugout",
                                "field": "asset_id",
                            }
                        },
                        "title": "Sessions",
                        "axis": {"labels": False, "ticks": False, "domain": False},
                    },
                    "yOffset": {
                        "field": "session_id",
                        "type": "nominal",
                        "bandPosition": 0.5,
                        "scale": {
                            "domain": {
                                "selection": "plugin_plugout",
                                "field": "session_id",
                            }
                        },
                    },
                    "color": {
                        "field": "asset",
                        "type": "nominal",
                        "legend": {
                            "title": "Asset",
                            "orient": "right",
                            "columns": 1,
                            "direction": "vertical",
                            "labelLimit": 200,
                        },
                    },
                    "tooltip": [
                        {
                            "field": "plug in",
                            "type": "temporal",
                            "title": "Plug-in",
                            "format": "%Y-%m-%d %H:%M:%S",
                        },
                        {
                            "field": "plug out",
                            "type": "temporal",
                            "title": "Plug-Out",
                            "format": "%Y-%m-%d %H:%M:%S",
                        },
                        {
                            "field": "asset_id",
                            "type": "nominal",
                            "title": "Asset ID",
                        },
                    ],
                },
            },
            # ---  Thick line: Start to Stop Charging ---
            {
                "transform": [
                    {
                        "calculate": "datum.asset_id + '_' + timeFormat(datum.event_start, '%Y-%m-%dT%H:%M:%S')",
                        "as": "session_id",
                    },
                    {
                        "filter": "datum.sensor_name == 'start charging' || datum.sensor_name == 'stop charging'"
                    },
                    {
                        "pivot": "sensor_name",
                        "value": "event_value",
                        "groupby": ["session_id", "asset", "asset_id"],
                    },
                    {"filter": {"selection": "start_stop_charging"}},
                ],
                "selection": {
                    "start_stop_charging": {
                        "type": "multi",
                        "encodings": ["color"],
                        "fields": ["asset"],
                        "bind": "legend",
                        "toggle": "event.ctrlKey",
                    }
                },
                "mark": {"type": "rule", "strokeWidth": 6},
                "encoding": {
                    "x": {
                        "field": "start charging",
                        "type": "temporal",
                        "scale": {
                            "domain": [
                                event_starts_after.timestamp() * 1000,
                                event_ends_before.timestamp() * 1000,
                            ]
                        },
                    },
                    "x2": {
                        "field": "stop charging",
                        "type": "temporal",
                        "scale": {
                            "domain": [
                                event_starts_after.timestamp() * 1000,
                                event_ends_before.timestamp() * 1000,
                            ]
                        },
                    },
                    "y": {
                        "field": "asset_id",
                        "type": "nominal",
                        "scale": {
                            "domain": {
                                "selection": "start_stop_charging",
                                "field": "asset_id",
                            }
                        },
                        "title": "Sessions",
                        "axis": {"labels": False, "ticks": False, "domain": False},
                    },
                    "yOffset": {
                        "field": "session_id",
                        "type": "nominal",
                        "bandPosition": 0.5,
                        "scale": {
                            "domain": {
                                "selection": "start_stop_charging",
                                "field": "session_id",
                            }
                        },
                    },
                    "color": {
                        "field": "asset",
                        "type": "nominal",
                        "legend": {
                            "orient": "right",
                            "columns": 1,
                            "direction": "vertical",
                            "labelLimit": 200,
                        },
                    },
                    "tooltip": [
                        {
                            "field": "start charging",
                            "type": "temporal",
                            "title": "Start Charging",
                            "format": "%Y-%m-%d %H:%M:%S",
                        },
                        {
                            "field": "stop charging",
                            "type": "temporal",
                            "title": "Stop Charging",
                            "format": "%Y-%m-%d %H:%M:%S",
                        },
                        {
                            "field": "asset_id",
                            "type": "nominal",
                            "title": "Asset ID",
                        },
                    ],
                },
            },
        ],
    }
    for idx, entry in enumerate(sensors_to_show_copy):
        title = entry.get("title")
        if title == "Power flow by type":
            sensors_to_show_copy[idx]["sensors"] = [
                sensor
                for sensor in entry["sensors"]
                if sensor.name == "charge points power"
            ]
    chart_specs = chart_for_multiple_sensors(
        sensors_to_show_copy,
        event_starts_after,
        event_ends_before,
        combine_legend,
        **override_chart_specs,
    )
    chart_specs["vconcat"] = [
        chart
        for chart in chart_specs["vconcat"]
        if chart["title"] in ["Prices", "Power flow by type"]
    ]
    chart_specs["vconcat"].insert(0, cp_chart)
    return chart_specs
