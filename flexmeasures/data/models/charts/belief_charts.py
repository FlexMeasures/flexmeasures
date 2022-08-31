from __future__ import annotations

from datetime import datetime

from flexmeasures.data.models.charts.defaults import FIELD_DEFINITIONS
from flexmeasures.utils.flexmeasures_inflection import capitalize


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
    event_start_field_definition = FIELD_DEFINITIONS["event_start"]
    if event_starts_after and event_ends_before:
        event_start_field_definition["scale"] = {
            "domain": [
                event_starts_after.timestamp() * 10**3,
                event_ends_before.timestamp() * 10**3,
            ]
        }
    resolution_in_ms = sensor.event_resolution.total_seconds() * 1000
    chart_specs = {
        "description": "A simple bar chart showing sensor data.",
        "title": capitalize(sensor.name) if sensor.name != sensor.sensor_type else None,
        "mark": {
            "type": "bar",
            "clip": True,
        },
        "encoding": {
            "x": event_start_field_definition,
            "x2": FIELD_DEFINITIONS["event_end"],
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
                FIELD_DEFINITIONS["source_name"],
                FIELD_DEFINITIONS["source_model"],
            ],
        },
        "transform": [
            {
                "calculate": f"datum.event_start + {resolution_in_ms}",
                "as": "event_end",
            },
        ],
    }
    for k, v in override_chart_specs.items():
        chart_specs[k] = v
    return chart_specs


def chart_for_multiple_sensors(
    sensors: list["Sensor"],  # noqa F821
    event_starts_after: datetime | None = None,
    event_ends_before: datetime | None = None,
    **override_chart_specs: dict,
):
    sensors_specs = []
    min_resolution_in_ms = (
        min(sensor.event_resolution for sensor in sensors).total_seconds() * 1000
    )
    for sensor in sensors:
        unit = sensor.unit if sensor.unit else "a.u."
        event_value_field_definition = dict(
            title=f"{capitalize(sensor.sensor_type)} ({unit})",
            format=[".3~r", unit],
            formatType="quantityWithUnitFormat",
            stack=None,
            **{
                **FIELD_DEFINITIONS["event_value"],
                **dict(field=sensor.id),
            },
        )
        event_start_field_definition = FIELD_DEFINITIONS["event_start"]
        if event_starts_after and event_ends_before:
            event_start_field_definition["scale"] = {
                "domain": [
                    event_starts_after.timestamp() * 10**3,
                    event_ends_before.timestamp() * 10**3,
                ]
            }
        shared_tooltip = [
            FIELD_DEFINITIONS["full_date"],
            {
                **event_value_field_definition,
                **dict(title=f"{capitalize(sensor.sensor_type)}"),
            },
            FIELD_DEFINITIONS["source_name"],
            FIELD_DEFINITIONS["source_model"],
        ]
        sensor_specs = {
            "title": capitalize(sensor.name)
            if sensor.name != sensor.sensor_type
            else None,
            "layer": [
                {
                    "mark": {
                        "type": "line",
                        "interpolate": "step-after",
                        "clip": True,
                    },
                    "encoding": {
                        "x": event_start_field_definition,
                        "y": event_value_field_definition,
                        "color": FIELD_DEFINITIONS["source_name"],
                        "detail": FIELD_DEFINITIONS["source"],
                    },
                },
                {
                    "mark": {
                        "type": "rect",
                        "y2": "height",
                        "opacity": 0,
                    },
                    "encoding": {
                        "x": event_start_field_definition,
                        "x2": FIELD_DEFINITIONS["event_end"],
                        "y": {
                            "condition": {
                                "test": "isNaN(datum['event_value'])",
                                **event_value_field_definition,
                            },
                            "value": 0,
                        },
                        "detail": FIELD_DEFINITIONS["source"],
                        "tooltip": shared_tooltip,
                    },
                    "transform": [
                        {
                            "calculate": f"datum.event_start + {min_resolution_in_ms}",
                            "as": "event_end",
                        },
                    ],
                },
                {
                    "mark": {
                        "type": "circle",
                        "opacity": 1,
                        "clip": True,
                    },
                    "encoding": {
                        "x": event_start_field_definition,
                        "y": event_value_field_definition,
                        "color": FIELD_DEFINITIONS["source_name"],
                        "detail": FIELD_DEFINITIONS["source"],
                        "size": {
                            "condition": {
                                "value": "200",
                                "test": {"param": "paintbrush", "empty": False},
                            },
                            "value": "0",
                        },
                        "tooltip": shared_tooltip,
                    },
                    "params": [
                        {
                            "name": "paintbrush",
                            "select": {
                                "type": "point",
                                "encodings": ["x"],
                                "on": "mouseover",
                                "nearest": False,
                            },
                        },
                    ],
                },
            ],
            "width": "container",
        }
        sensors_specs.append(sensor_specs)
    chart_specs = dict(
        description="A vertically concatenated chart showing sensor data.",
        vconcat=[*sensors_specs],
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
