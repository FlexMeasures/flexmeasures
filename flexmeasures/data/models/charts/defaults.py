from __future__ import annotations

from functools import wraps
from typing import Callable

import altair as alt


FONT_SIZE = 16
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
        "color": "#bbbbbb",
        "opacity": 0.3,
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
LEGIBILITY_DEFAULTS = dict(
    config=dict(
        axis=dict(
            titleFontSize=FONT_SIZE,
            labelFontSize=FONT_SIZE,
        ),
        axisY={"titleAngle": 0, "titleAlign": "left", "titleY": -15, "titleX": -40},
        title=dict(
            fontSize=FONT_SIZE,
        ),
        legend=dict(
            titleFontSize=FONT_SIZE,
            labelFontSize=FONT_SIZE,
            labelLimit=None,
            orient="bottom",
            columns=1,
            direction="vertical",
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
            if include_annotations:
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
