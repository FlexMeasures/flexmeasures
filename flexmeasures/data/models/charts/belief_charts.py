from __future__ import annotations

from datetime import datetime, timedelta

from flexmeasures.data.models.charts.defaults import FIELD_DEFINITIONS, REPLAY_RULER
from flexmeasures.utils.flexmeasures_inflection import (
    capitalize,
    join_words_into_a_list,
)
from flexmeasures.utils.coding_utils import flatten_unique
from flexmeasures.utils.unit_utils import (
    is_power_unit,
    is_energy_unit,
    is_energy_price_unit,
)


def bar_chart(
    sensor: "Sensor",  # noqa F821
    event_starts_after: datetime | None = None,
    event_ends_before: datetime | None = None,
    **override_chart_specs: dict,
):
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
    chart_specs = {
        "description": "A simple bar chart showing sensor data.",
        # the sensor type is already shown as the y-axis title (avoid redundant info)
        "title": capitalize(sensor.name) if sensor.name != sensor.sensor_type else None,
        "layer": [
            {
                "mark": {
                    "type": "bar",
                    "clip": True,
                    "width": {"band": 0.999},
                },
                "encoding": {
                    "x": event_start_field_definition,
                    "y": event_value_field_definition,
                    "color": FIELD_DEFINITIONS["source_name"],
                    "detail": FIELD_DEFINITIONS["source"],
                    "opacity": {"value": 0.7},
                    "tooltip": [
                        FIELD_DEFINITIONS["full_date"],
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
            },
            REPLAY_RULER,
        ],
    }
    for k, v in override_chart_specs.items():
        chart_specs[k] = v
    return chart_specs


def daily_heatmap(
    sensor: "Sensor",  # noqa F821
    event_starts_after: datetime | None = None,
    event_ends_before: datetime | None = None,
    **override_chart_specs: dict,
):
    unit = sensor.unit if sensor.unit else "a.u."
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
            "unit": "hoursminutesseconds",
            "step": sensor.event_resolution.total_seconds(),
        },
        axis={
            "labelExpr": "timeFormat(datum.value, '%H:%M')",
            "labelFlush": False,
            "labelOverlap": True,
            "labelSeparation": 1,
        },
        scale={
            "domain": [
                {"hours": 0},
                {"hours": 24},
            ]
        },
    )
    event_start_date_field_definition = dict(
        field="event_start",
        type="temporal",
        title=None,
        timeUnit={
            "unit": "yearmonthdate",
        },
        axis={
            "tickCount": "day",
            # Center align the date labels
            "labelOffset": {
                "expr": "(scale('y', 24 * 60 * 60 * 1000) - scale('y', 0)) / 2"
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
        "description": "A daily heatmap showing sensor data.",
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
                        "timeUnit": "hoursminutesseconds",
                    },
                    "y": {
                        "field": "belief_time",
                        "type": "temporal",
                        "timeUnit": "yearmonthdate",
                    },
                    "yOffset": {
                        "value": {
                            "expr": "(scale('y', 24 * 60 * 60 * 1000) - scale('y', 0))"
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
    timezone, mark, event_value_field_definition, event_start_field_definition, tooltip
) -> dict:
    """Special layer for showing data during the daylight savings time transition in fall."""
    return {
        "mark": mark,
        "encoding": {
            "x": event_start_field_definition,
            "y": {
                "field": "dst_transition_event_start",
                "type": "temporal",
                "title": None,
                "timeUnit": {"unit": "yearmonthdatehours", "step": 12},
            },
            "y2": {
                "field": "dst_transition_event_start_next",
                "timeUnit": {"unit": "yearmonthdatehours", "step": 12},
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
                "filter": "timezoneoffset(datum.event_start) < timezoneoffset(datum.event_start + 60 * 60 * 1000) || timezoneoffset(datum.event_start) > timezoneoffset(datum.event_start - 60 * 60 * 1000)"
            },
            {
                # Push the more recent hour into the second 12-hour bin
                "calculate": "timezoneoffset(datum.event_start + 60 * 60 * 1000) > timezoneoffset(datum.event_start) ? datum.event_start : datum.event_start + 12 * 60 * 60 * 1000",
                "as": "dst_transition_event_start",
            },
            {
                # Calculate a time point in the next 12-hour bin
                "calculate": "datum.dst_transition_event_start + 12 * 60 * 60 * 1000 - 60 * 60 * 1000",
                "as": "dst_transition_event_start_next",
            },
            {
                "calculate": "datum.source.name + ' (ID: ' + datum.source.id + ')'",
                "as": "source_name_and_id",
            },
        ],
    }


def chart_for_multiple_sensors(
    sensors_to_show: list["Sensor", list["Sensor"]],  # noqa F821
    event_starts_after: datetime | None = None,
    event_ends_before: datetime | None = None,
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

    # Set up field definition for sensor descriptions
    sensor_field_definition = FIELD_DEFINITIONS["sensor_description"].copy()
    sensor_field_definition["scale"] = dict(
        domain=[sensor.to_dict()["description"] for sensor in all_shown_sensors]
    )

    sensors_specs = []
    for s in sensors_to_show:
        # List the sensors that go into one row
        if isinstance(s, list):
            row_sensors: list["Sensor"] = s  # noqa F821
        else:
            row_sensors: list["Sensor"] = [s]  # noqa F821

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
                field="sensor.name",
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
            "title": join_words_into_a_list(
                [
                    f"{capitalize(sensor.name)}"
                    for sensor in row_sensors
                    # the sensor type is already shown as the y-axis title (avoid redundant info)
                    if sensor.name != sensor.sensor_type
                ]
            ),
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
        spacing=100,
        bounds="flush",
    )
    chart_specs["config"] = {
        "view": {"continuousWidth": 800, "continuousHeight": 150},
        "autosize": {"type": "fit-x", "contains": "padding"},
    }
    chart_specs["resolve"] = {"scale": {"x": "shared"}}
    for k, v in override_chart_specs.items():
        chart_specs[k] = v
    return chart_specs


def determine_shared_unit(sensors: list["Sensor"]) -> str:  # noqa F821
    units = list(set([sensor.unit for sensor in sensors if sensor.unit]))

    # Replace with 'a.u.' in case of mixing units
    shared_unit = units[0] if len(units) == 1 else "a.u."

    # Replace with 'dimensionless' in case of empty unit
    return shared_unit if shared_unit else "dimensionless"


def determine_shared_sensor_type(sensors: list["Sensor"]) -> str:  # noqa F821
    sensor_types = list(set([sensor.sensor_type for sensor in sensors]))

    # Return the sole sensor type
    if len(sensor_types) == 1:
        return sensor_types[0]

    # Check the units for common cases
    shared_unit = determine_shared_unit(sensors)
    if is_power_unit(shared_unit):
        return "power"
    elif is_energy_unit(shared_unit):
        return "energy"
    elif is_energy_price_unit(shared_unit):
        return "energy price"
    return "value"


def create_line_layer(
    sensors: list["Sensor"],  # noqa F821
    event_start_field_definition: dict,
    event_value_field_definition: dict,
    sensor_field_definition: dict,
):
    event_resolutions = list(set([sensor.event_resolution for sensor in sensors]))
    assert all(res == timedelta(0) for res in event_resolutions) or all(
        res != timedelta(0) for res in event_resolutions
    ), "Sensors shown within one row must all be instantaneous (zero event resolution) or all be non-instantatneous (non-zero event resolution)."
    event_resolution = event_resolutions[0]
    line_layer = {
        "mark": {
            "type": "line",
            "interpolate": "step-after"
            if event_resolution != timedelta(0)
            else "linear",
            "clip": True,
        },
        "encoding": {
            "x": event_start_field_definition,
            "y": event_value_field_definition,
            "color": sensor_field_definition,
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
    }
    return line_layer


def create_circle_layer(
    sensors: list["Sensor"],  # noqa F821
    event_start_field_definition: dict,
    event_value_field_definition: dict,
    sensor_field_definition: dict,
    shared_tooltip: list,
):
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
            "y": event_value_field_definition,
            "color": sensor_field_definition,
            "size": {
                "condition": {"value": "200", "test": {"or": or_conditions}},
                "value": "0",
            },
            "tooltip": shared_tooltip,
        },
        "params": params,
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
