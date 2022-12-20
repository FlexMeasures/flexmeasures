from __future__ import annotations

from datetime import datetime, timedelta

from flexmeasures.data.models.charts.defaults import FIELD_DEFINITIONS, REPLAY_RULER
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
        "layer": [
            {
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
                        FIELD_DEFINITIONS["source_name_and_id"],
                        FIELD_DEFINITIONS["source_model"],
                    ],
                },
                "transform": [
                    {
                        "calculate": f"datum.event_start + {resolution_in_ms}",
                        "as": "event_end",
                    },
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


def chart_for_multiple_sensors(
    sensors: list["Sensor"],  # noqa F821
    event_starts_after: datetime | None = None,
    event_ends_before: datetime | None = None,
    **override_chart_specs: dict,
):
    sensors_specs = []
    condition = list(
        sensor.event_resolution
        for sensor in sensors
        if sensor.event_resolution > timedelta(0)
    )
    minimum_non_zero_resolution_in_ms = (
        min(condition).total_seconds() * 1000 if any(condition) else 0
    )
    for sensor in sensors:
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
        shared_tooltip = [
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
                **dict(title=f"{capitalize(sensor.sensor_type)}"),
            },
            FIELD_DEFINITIONS["source_name_and_id"],
            FIELD_DEFINITIONS["source_model"],
        ]
        line_layer = {
            "mark": {
                "type": "line",
                "interpolate": "step-after"
                if sensor.event_resolution != timedelta(0)
                else "linear",
                "clip": True,
            },
            "encoding": {
                "x": event_start_field_definition,
                "y": event_value_field_definition,
                "color": FIELD_DEFINITIONS["source_name"],
                "strokeDash": {
                    "field": "belief_horizon",
                    "type": "quantitative",
                    "bin": {
                        # Divide belief horizons into 2 bins by setting a very large bin size.
                        # The bins should be defined as follows: ex ante (>0) and ex post (<=0),
                        # but because the bin anchor is included in the ex-ante bin,
                        # and 0 belief horizons should be attributed to the ex-post bin,
                        # (and belief horizons are given with 1 ms precision,)
                        # the bin anchor is set at 1 ms before knowledge time to obtain: ex ante (>=1) and ex post (<1).
                        "anchor": 1,
                        "step": 8640000000000000,  # JS max ms for a Date object (NB 10 times less than Python max ms)
                        # "step": timedelta.max.total_seconds() * 10**2,
                    },
                    "legend": {
                        # Belief horizons binned as 1 ms contain ex-ante beliefs; the other bin contains ex-post beliefs
                        "labelExpr": "datum.label > 0 ? 'ex ante' : 'ex post'",
                        "title": "Recorded",
                    },
                    "scale": {
                        # Positive belief horizons are clamped to 1, negative belief horizons are clamped to 0
                        "domain": [1, 0],
                        # belief horizons >= 1 ms get a dashed line, belief horizons < 1 ms get a solid line
                        "range": [[1, 2], [1, 0]],
                    },
                },
                "detail": FIELD_DEFINITIONS["source"],
            },
        }
        sensor_specs = {
            "title": capitalize(sensor.name)
            if sensor.name != sensor.sensor_type
            else None,
            "transform": [{"filter": f"datum.sensor.id == {sensor.id}"}],
            "layer": [
                line_layer,
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
                            "calculate": f"datum.event_start + {minimum_non_zero_resolution_in_ms}",
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
                REPLAY_RULER,
            ],
            "width": "container",
        }
        sensors_specs.append(sensor_specs)
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
