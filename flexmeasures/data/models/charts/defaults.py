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
]


def _hovered_time_expr(param: str) -> str:
    """Expression yielding the event_start value captured by a point selection param.

    Handles both scalar and array-valued selection signals.
    """
    value = f"{param}['event_start']"
    return f"(isArray({value}) ? {value}[0] : {value})"


def _time_captured_test(param: str) -> str:
    """Expression testing whether the param captured a time at all."""
    return f"isValid({param}) && isValid({param}['event_start'])"


def _band_hover_test(param: str) -> str:
    """Expression testing whether the captured time falls within the annotation band."""
    time_expr = _hovered_time_expr(param)
    return (
        f"{_time_captured_test(param)}"
        f" && {time_expr} >= datum.start && {time_expr} < datum.end"
    )


def _instant_hover_test(param: str, tolerance_ms: int) -> str:
    """Expression testing whether the captured time is close to the instant annotation."""
    time_expr = _hovered_time_expr(param)
    return (
        f"{_time_captured_test(param)}"
        f" && abs({time_expr} - datum.start) <= {tolerance_ms}"
    )


def _annotation_hover_test(param: str, tolerance_ms: int) -> str:
    """Expression testing whether the captured time matches the annotation (band or instant)."""
    return (
        f"(datum.start != datum.end && {_band_hover_test(param)})"
        f" || (datum.start == datum.end && {_instant_hover_test(param, tolerance_ms)})"
    )


def create_annotation_layers(
    annotations_dataset_name: str, row_index: int, resolution_ms: int = 3600 * 1000
) -> tuple[list[dict], list[dict]]:
    """Create annotation layers for one subchart (row) of a vconcat chart.

    All rows bind to the same named annotations dataset, but each row gets its
    own hover/pin params, so that hovering an annotation band darkens it only
    in the hovered subchart, while the other subcharts keep the light shading.

    The hover/pin params capture the event_start of the hovered/clicked datum
    (events bubble up to the view level, so they also fire on the invisible
    full-height data hit-rect above). Annotation highlighting then tests
    whether the captured time falls within the annotation window, with a
    one-resolution-bin tolerance for instant (zero-duration) annotations.
    This way, the data tooltip keeps working inside annotation bands.

    Returns two lists of layers:
    - background layers (drawn behind the data):
      - a full-height rect band for annotations with a non-zero duration
      - a rule for instant annotations
      - a triangle marker at the top of each instant-annotation rule
    - foreground layers (drawn on top of the data):
      - a text mark showing the annotation content below the subchart
        (in the gap between the axis labels and the next subchart)
        when the annotation is hovered or pinned
    """
    hover_param = f"annotation_hover_time_{row_index}"
    pin_param = f"annotation_pin_time_{row_index}"
    hover_test = _annotation_hover_test(hover_param, resolution_ms)
    pin_test = _annotation_hover_test(pin_param, resolution_ms)
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
                        "test": _band_hover_test(pin_param),
                        "value": ANNOTATION_SELECT_OPACITY,
                    },
                    {
                        "test": _band_hover_test(hover_param),
                        "value": ANNOTATION_HOVER_OPACITY,
                    },
                ],
                "value": ANNOTATION_RESTING_OPACITY,
            },
        },
        "params": [
            {
                "name": hover_param,
                "select": {
                    "type": "point",
                    "fields": ["event_start"],
                    "on": "mouseover",
                    "clear": "mouseout",
                },
            },
            {
                "name": pin_param,
                "select": {"type": "point", "fields": ["event_start"]},
            },
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
                        "test": _instant_hover_test(pin_param, resolution_ms),
                        "value": 1,
                    },
                    {
                        "test": _instant_hover_test(hover_param, resolution_ms),
                        "value": 0.9,
                    },
                ],
                "value": 0.5,
            },
        },
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
            "size": 200,
            "clip": True,
        },
        "encoding": {
            "x": start_field_definition,
            "y": {"value": 7},
            "color": ANNOTATION_COLOR_ENCODING,
            "opacity": {
                "condition": [
                    {
                        "test": _instant_hover_test(pin_param, resolution_ms),
                        "value": 1,
                    },
                    {
                        "test": _instant_hover_test(hover_param, resolution_ms),
                        "value": 1,
                    },
                ],
                "value": 0.9,
            },
        },
    }
    text_layer = {
        "name": f"annotation_text_{row_index}",
        "data": {"name": annotations_dataset_name},
        "transform": [*ANNOTATION_SHARED_TRANSFORMS],
        "mark": {
            "type": "text",
            "clip": False,
            # Anchor the text to the bottom of the subchart and offset it into
            # the gap between the datetime axis labels and the next subchart,
            # so showing it does not affect the chart layout
            "y": "height",
            "dy": FONT_SIZE + ANNOTATION_MARGIN,
            "baseline": "top",
            "align": "left",
            "fontSize": FONT_SIZE,
            "fontStyle": "italic",
        },
        "encoding": {
            "x": start_field_definition,
            "text": {"type": "nominal", "field": "content"},
            "color": ANNOTATION_COLOR_ENCODING,
            "opacity": {
                "condition": [
                    {"test": pin_test, "value": 1},
                    {"test": hover_test, "value": 1},
                ],
                "value": 0,
            },
        },
    }
    return [band_layer, rule_layer, marker_layer], [text_layer]


def _row_resolution_ms(row_specs: dict, default_ms: int = 3600 * 1000) -> int:
    """Find the time resolution (in ms) of a subchart row from its x-encoding time unit."""
    for layer in row_specs.get("layer", []):
        time_unit = layer.get("encoding", {}).get("x", {}).get("timeUnit")
        if isinstance(time_unit, dict) and "step" in time_unit:
            try:
                return int(float(time_unit["step"]) * 1000)
            except (TypeError, ValueError):
                continue
    return default_ms


def add_annotation_layers_to_vconcat(
    chart_specs: dict, annotations_dataset_name: str
) -> None:
    """Add annotation layers to each subchart of a vertically concatenated chart.

    The band, rule and marker layers are drawn behind the data layers,
    keeping the data (and its tooltip hit-area) fully interactive,
    while the annotation text layer is drawn on top.
    """
    for row_index, row_specs in enumerate(chart_specs.get("vconcat", [])):
        if "layer" not in row_specs:
            continue
        background_layers, foreground_layers = create_annotation_layers(
            annotations_dataset_name,
            row_index,
            resolution_ms=_row_resolution_ms(row_specs),
        )
        row_specs["layer"] = [
            *background_layers,
            *row_specs["layer"],
            *foreground_layers,
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
