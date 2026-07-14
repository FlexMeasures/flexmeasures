from __future__ import annotations

from functools import wraps
from numpy import pi
from typing import Callable

import altair as alt


FONT_SIZE = 16
STROKE_WIDTH = 2
ANNOTATION_MARGIN = 16
HEIGHT = 300
WIDTH = "container"
REDUCED_HEIGHT = REDUCED_WIDTH = 60
SELECTOR_COLOR = "darkred"
TIME_FORMAT = "%H:%M on %A %b %e, %Y"
# Use default timeFormat for date or second labels, and use 24-hour clock notation for other (hour and minute) labels
FORMAT_24H = "(hours(datum.value) == 0 & minutes(datum.value) == 0) | seconds(datum.value) != 0 ? timeFormat(datum.value) : timeFormat(datum.value, '%H:%M')"
TIME_SELECTION_TOOLTIP = "Click and drag to select a time window"
FIELD_DEFINITIONS = {
    "event_start": dict(
        field="event_start",
        type="temporal",
        title=None,
        axis={"labelExpr": FORMAT_24H, "labelOverlap": True, "labelSeparation": 1},
    ),
    "event_value": dict(
        field="event_value",
        type="quantitative",
    ),
    "sensor": dict(
        field="sensor.id",
        type="nominal",
        title=None,
    ),
    "sensor_name": dict(
        field="sensor.name",
        type="nominal",
        title="Sensor",
    ),
    "sensor_description": dict(
        field="sensor.description",
        type="nominal",
        title="Sensor",
    ),
    "source": dict(
        field="source.id",
        type="nominal",
        title=None,
    ),
    "source_type": dict(
        field="source.type",
        type="nominal",
        title="Type",
    ),
    "source_display_type": dict(
        field="source.display_type",
        type="nominal",
        title="Type",
    ),
    "source_name": dict(
        field="source.name",
        type="nominal",
        title="Source",
    ),
    "source_model": dict(
        field="source.model",
        type="nominal",
        title="Model",
    ),
    "source_version": dict(
        field="source.version",
        type="nominal",
        title="Version",
    ),
    "full_date": dict(
        field="full_date",
        type="nominal",
        title="Time and date",
    ),
    "source_name_and_id": dict(
        field="source_name_and_id",
        type="nominal",
        title="Source",
    ),
    "source_legend_label": dict(
        field="source_legend_label",
        type="nominal",
        title="Source",
    ),
}
REPLAY_RULER = {
    "data": {"name": "replay"},
    "mark": {
        "type": "rule",
    },
    "encoding": {
        "x": {
            "field": "belief_time",
            "type": "temporal",
        },
    },
}
SHADE_LAYER = {
    "mark": {
        "type": "bar",
        "size": HEIGHT,
    },
    "encoding": {
        "x": dict(
            field="start",
            type="temporal",
            title=None,
        ),
        "x2": dict(
            field="end",
            type="temporal",
            title=None,
        ),
        "color": {
            "condition": [
                {
                    "param": "select",
                    "empty": False,
                    "value": "var(--secondary-color)",  # highlight color on select
                },
                {
                    "param": "highlight",
                    "empty": False,
                    "value": "var(--secondary-hover-color)",  # highlight color on hover
                },
            ],
            "value": "var(--gray)",  # default color
        },
        "opacity": {
            "condition": [
                {
                    "param": "select",
                    "empty": False,
                    "value": 0.8,
                },
                {
                    "param": "highlight",
                    "empty": False,
                    "value": 0.7,
                },
            ],
            "value": 0.3,
        },
    },
    "params": [
        {
            "name": "highlight",
            "select": {"type": "point", "on": "mouseover"},
        },
        {"name": "select", "select": "point"},
    ],
}
TEXT_LAYER = {
    "mark": {
        "type": "text",
        "clip": False,
        "y": HEIGHT,
        "dy": FONT_SIZE + ANNOTATION_MARGIN,
        "baseline": "top",
        "align": "left",
        "fontSize": FONT_SIZE,
        "fontStyle": "italic",
    },
    "encoding": {
        "x": dict(
            field="start",
            type="temporal",
            title=None,
        ),
        "text": {"type": "nominal", "field": "content"},
        "opacity": {
            "condition": [
                {
                    "param": "select",
                    "empty": False,
                    "value": 1,
                },
                {
                    "param": "highlight",
                    "empty": False,
                    "value": 1,
                },
            ],
            "value": 0,
        },
    },
}
# Warm warning hue for 'alert' annotations, legible in both light and dark themes
ANNOTATION_ALERT_COLOR = "#d9822b"
ANNOTATION_DEFAULT_COLOR = "var(--gray)"
ANNOTATION_RESTING_OPACITY = 0.2
ANNOTATION_HOVER_OPACITY = 0.55
ANNOTATION_SELECT_OPACITY = 0.65

ANNOTATION_COLOR_ENCODING = {
    "condition": [
        {
            "test": "datum.type == 'alert'",
            "value": ANNOTATION_ALERT_COLOR,
        },
    ],
    "value": ANNOTATION_DEFAULT_COLOR,
}
ANNOTATION_SHARED_TRANSFORMS = [
    # Alias the event_start field, so that x-encoded selections defined in
    # sibling layers can compute their tuples from annotation datums, too
    {"calculate": "datum.start", "as": "event_start"},
    # Join the (wrapped) content lines into a single text for the tooltip
    {"calculate": "join(datum.content, ' ')", "as": "content_text"},
]
ANNOTATION_TOOLTIP = [
    {"field": "content_text", "type": "nominal", "title": "Annotation"},
    {"field": "type", "type": "nominal", "title": "Type"},
    {"field": "source", "type": "nominal", "title": "Source"},
    {"field": "start", "type": "temporal", "title": "From", "format": TIME_FORMAT},
    {"field": "end", "type": "temporal", "title": "Until", "format": TIME_FORMAT},
]


def create_annotation_layers(
    annotations_dataset_name: str, row_index: int
) -> list[dict]:
    """Create annotation layers for one subchart (row) of a vconcat chart.

    All rows bind to the same named annotations dataset, but each row gets its
    own hover/select params, so that hovering an annotation band darkens it only
    in the hovered subchart, while the other subcharts keep the light shading.

    Returns three layers:
    - a full-height rect band for annotations with a non-zero duration
    - a rule for instant (zero-duration) annotations
    - a triangle marker at the top of each instant-annotation rule
    """
    highlight_param = f"annotation_highlight_{row_index}"
    select_param = f"annotation_select_{row_index}"
    rule_highlight_param = f"annotation_rule_highlight_{row_index}"
    rule_select_param = f"annotation_rule_select_{row_index}"
    start_field_definition = dict(
        field="start",
        type="temporal",
        title=None,
    )
    band_layer = {
        "name": f"annotation_band_{row_index}",
        "data": {"name": annotations_dataset_name},
        "transform": [
            {"filter": "datum.start != datum.end"},
            *ANNOTATION_SHARED_TRANSFORMS,
        ],
        "mark": {"type": "rect", "clip": True},
        "encoding": {
            "x": start_field_definition,
            "x2": dict(field="end", title=None),
            "color": ANNOTATION_COLOR_ENCODING,
            "opacity": {
                "condition": [
                    {
                        "param": select_param,
                        "empty": False,
                        "value": ANNOTATION_SELECT_OPACITY,
                    },
                    {
                        "param": highlight_param,
                        "empty": False,
                        "value": ANNOTATION_HOVER_OPACITY,
                    },
                ],
                "value": ANNOTATION_RESTING_OPACITY,
            },
            "tooltip": ANNOTATION_TOOLTIP,
        },
        "params": [
            {
                "name": highlight_param,
                "select": {"type": "point", "on": "mouseover", "clear": "mouseout"},
            },
            {"name": select_param, "select": "point"},
        ],
    }
    rule_layer = {
        "name": f"annotation_rule_{row_index}",
        "data": {"name": annotations_dataset_name},
        "transform": [
            {"filter": "datum.start == datum.end"},
            *ANNOTATION_SHARED_TRANSFORMS,
        ],
        "mark": {"type": "rule", "clip": True, "strokeWidth": 2},
        "encoding": {
            "x": start_field_definition,
            "color": ANNOTATION_COLOR_ENCODING,
            "opacity": {
                "condition": [
                    {
                        "param": rule_select_param,
                        "empty": False,
                        "value": 1,
                    },
                    {
                        "param": rule_highlight_param,
                        "empty": False,
                        "value": 0.9,
                    },
                ],
                "value": 0.5,
            },
            "tooltip": ANNOTATION_TOOLTIP,
        },
        "params": [
            {
                "name": rule_highlight_param,
                "select": {"type": "point", "on": "mouseover", "clear": "mouseout"},
            },
            {"name": rule_select_param, "select": "point"},
        ],
    }
    marker_layer = {
        "name": f"annotation_marker_{row_index}",
        "data": {"name": annotations_dataset_name},
        "transform": [
            {"filter": "datum.start == datum.end"},
            *ANNOTATION_SHARED_TRANSFORMS,
        ],
        "mark": {
            "type": "point",
            "shape": "triangle-down",
            "filled": True,
            "size": 60,
            "clip": True,
        },
        "encoding": {
            "x": start_field_definition,
            "y": {"value": 4},
            "color": ANNOTATION_COLOR_ENCODING,
            "opacity": {"value": 0.9},
        },
    }
    return [band_layer, rule_layer, marker_layer]


def add_annotation_layers_to_vconcat(
    chart_specs: dict, annotations_dataset_name: str
) -> None:
    """Add annotation layers to each subchart of a vertically concatenated chart.

    The layers are appended on top of the data layers, so that the annotation
    bands can receive hover events and show their own tooltip.
    """
    for row_index, row_specs in enumerate(chart_specs.get("vconcat", [])):
        if "layer" not in row_specs:
            continue
        row_specs["layer"] = [
            *row_specs["layer"],
            *create_annotation_layers(annotations_dataset_name, row_index),
        ]


LEGIBILITY_DEFAULTS = dict(
    config=dict(
        axis=dict(
            titleFontSize=FONT_SIZE,
            labelFontSize=FONT_SIZE,
        ),
        axisY={"titleAngle": 0, "titleAlign": "left", "titleY": -15, "titleX": -40},
        title=dict(
            fontSize=FONT_SIZE * 1.25,
        ),
        legend=dict(
            titleFontSize=FONT_SIZE,
            labelFontSize=FONT_SIZE,
            labelLimit=None,
            orient="bottom",
            columns=1,
            direction="vertical",
            symbolSize=(
                100 if STROKE_WIDTH <= 2 else 100 + 800 / 3 / pi * (STROKE_WIDTH - 2)
            ),
            symbolStrokeWidth=STROKE_WIDTH,
            labelOffset=2 * STROKE_WIDTH,
        ),
    ),
)
vega_lite_field_mapping = {
    "title": "text",
    "mark": "type",
}


def apply_chart_defaults(fn):
    @wraps(fn)
    def decorated_chart_specs(*args, **kwargs) -> dict:
        """:returns: dict with vega-lite specs, even when applied to an Altair chart."""
        dataset_name = kwargs.pop("dataset_name", None)
        include_annotations = kwargs.pop("include_annotations", None)
        if isinstance(fn, Callable):
            # function that returns a chart specification
            chart_specs: dict | alt.TopLevelMixin = fn(*args, **kwargs)
        else:
            # not a function, but a direct chart specification
            chart_specs: dict | alt.TopLevelMixin = fn
        if isinstance(chart_specs, alt.TopLevelMixin):
            chart_specs = chart_specs.to_dict()
            chart_specs.pop("$schema")

        # Add transform function to calculate full date
        if "transform" not in chart_specs:
            chart_specs["transform"] = []
        chart_specs["transform"].append(
            {
                "as": "full_date",
                "calculate": f"timeFormat(datum.event_start, '{TIME_FORMAT}')",
            }
        )

        if dataset_name:
            chart_specs["data"] = {"name": dataset_name}
            if include_annotations and "vconcat" in chart_specs:
                # Add annotation bands to each subchart of a vconcat chart
                add_annotation_layers_to_vconcat(
                    chart_specs, dataset_name + "_annotations"
                )
            elif include_annotations:
                annotation_shades_layer = SHADE_LAYER
                annotation_text_layer = TEXT_LAYER
                annotation_shades_layer["data"] = {
                    "name": dataset_name + "_annotations"
                }
                annotation_text_layer["data"] = {"name": dataset_name + "_annotations"}
                chart_specs = {
                    "layer": [
                        annotation_shades_layer,
                        chart_specs,
                        annotation_text_layer,
                    ]
                }

        # Fall back to default height and width, if needed
        if "height" not in chart_specs:
            chart_specs["height"] = HEIGHT
        if "width" not in chart_specs:
            chart_specs["width"] = WIDTH

        # Improve default legibility
        chart_specs = merge_vega_lite_specs(
            LEGIBILITY_DEFAULTS,
            chart_specs,
        )

        return chart_specs

    return decorated_chart_specs


def merge_vega_lite_specs(child: dict, parent: dict) -> dict:
    """Merge nested dictionaries, with child inheriting values from parent.

    Child values are updated with parent values if they exist.
    In case a field is a string and that field is updated with some dict,
    the string is moved inside the dict under a field defined in vega_lite_field_mapping.
    For example, 'title' becomes 'text' and 'mark' becomes 'type'.
    """
    d = {}
    for k in set().union(child, parent):
        if k in parent and k in child:
            if isinstance(child[k], str) and isinstance(parent[k], str):
                child[k] = parent[k]
            elif isinstance(child[k], str):
                child[k] = {vega_lite_field_mapping.get(k, "type"): child[k]}
            elif isinstance(parent[k], str):
                parent[k] = {vega_lite_field_mapping.get(k, "type"): parent[k]}
        if (
            k in parent
            and isinstance(parent[k], dict)
            and k in child
            and isinstance(child[k], dict)
        ):
            v = merge_vega_lite_specs(child[k], parent[k])
        elif k in parent:
            v = parent[k]
        else:
            v = child[k]
        d[k] = v
    return d
