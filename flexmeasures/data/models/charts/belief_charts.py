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
        format=[".3s", unit],
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
    chart_specs = {
        "description": "A simple bar chart showing sensor data.",
        "title": capitalize(sensor.name) if sensor.name != sensor.sensor_type else None,
        "mark": "bar",
        "encoding": {
            "x": event_start_field_definition,
            "x2": FIELD_DEFINITIONS["event_end"],
            "y": event_value_field_definition,
            "color": FIELD_DEFINITIONS["source"],
            "opacity": {"value": 0.7},
            "tooltip": [
                FIELD_DEFINITIONS["full_date"],
                {
                    **event_value_field_definition,
                    **dict(title=f"{capitalize(sensor.sensor_type)}"),
                },
                FIELD_DEFINITIONS["source"],
            ],
        },
        "transform": [
            {
                "calculate": f"datum.event_start + {sensor.event_resolution.total_seconds() * 1000}",
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
    for sensor in sensors:
        unit = sensor.unit if sensor.unit else "a.u."
        event_value_field_definition = dict(
            title=f"{capitalize(sensor.sensor_type)} ({unit})",
            format=[".3s", unit],
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
        sensor_specs = {
            "title": capitalize(sensor.name)
            if sensor.name != sensor.sensor_type
            else None,
            "layer": [
                {
                    "mark": {
                        "type": "line",
                        "interpolate": "step-after",
                    },
                    "encoding": {
                        "x": event_start_field_definition,
                        "y": event_value_field_definition,
                    },
                },
                {
                    "mark": {
                        "type": "circle",
                        "opacity": 1,
                    },
                    "encoding": {
                        "x": event_start_field_definition,
                        "y": event_value_field_definition,
                        "size": {
                            "condition": {
                                "value": "200",
                                "test": {"param": "paintbrush", "empty": False},
                            },
                            "value": "0",
                        },
                        "tooltip": [
                            FIELD_DEFINITIONS["full_date"],
                            {
                                **event_value_field_definition,
                                **dict(title=f"{capitalize(sensor.sensor_type)}"),
                            },
                        ],
                    },
                    "params": [
                        {
                            "name": "paintbrush",
                            "select": {
                                "type": "point",
                                "encodings": ["x"],
                                "on": "mouseover",
                                "nearest": True,
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
        "legend": {"orient": "bottom", "columns": 1, "direction": "vertical"},
    }
    chart_specs["resolve"] = {"scale": {"x": "shared"}}
    for k, v in override_chart_specs.items():
        chart_specs[k] = v
    return chart_specs
