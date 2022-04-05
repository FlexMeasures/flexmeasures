from functools import wraps
from typing import Callable, Union

import altair as alt


FONT_SIZE = 16
HEIGHT = 300
WIDTH = 600
REDUCED_HEIGHT = REDUCED_WIDTH = 60
SELECTOR_COLOR = "darkred"
TIME_FORMAT = "%I:%M %p on %A %b %e, %Y"
TIME_SELECTION_TOOLTIP = "Click and drag to select a time window"
FIELD_DEFINITIONS = {
    "event_start": dict(
        field="event_start",
        type="temporal",
        title=None,
    ),
    "event_end": dict(
        field="event_end",
        type="temporal",
        title=None,
    ),
    "event_value": dict(
        field="event_value",
        type="quantitative",
    ),
    "source": dict(
        field="source",
        type="nominal",
        title="Source",
    ),
    "full_date": dict(
        field="full_date",
        type="nominal",
        title="Time and date",
    ),
}
LEGIBILITY_DEFAULTS = dict(
    config=dict(
        axis=dict(
            titleFontSize=FONT_SIZE,
            labelFontSize=FONT_SIZE,
        )
    ),
    title=dict(fontSize=FONT_SIZE),
    encoding=dict(
        color=dict(
            dict(
                legend=dict(
                    titleFontSize=FONT_SIZE,
                    labelFontSize=FONT_SIZE,
                )
            )
        )
    ),
)
vega_lite_field_mapping = {
    "title": "text",
    "mark": "type",
}


def apply_chart_defaults(fn):
    @wraps(fn)
    def decorated_chart_specs(*args, **kwargs):
        dataset_name = kwargs.pop("dataset_name", None)
        if isinstance(fn, Callable):
            # function that returns a chart specification
            chart_specs: Union[dict, alt.TopLevelMixin] = fn(*args, **kwargs)
        else:
            # not a function, but a direct chart specification
            chart_specs: Union[dict, alt.TopLevelMixin] = fn
        if isinstance(chart_specs, alt.TopLevelMixin):
            chart_specs = chart_specs.to_dict()
            chart_specs.pop("$schema")
        if dataset_name:
            chart_specs["data"] = {"name": dataset_name}

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

        # Add transform function to calculate full date
        if "transform" not in chart_specs:
            chart_specs["transform"] = []
        chart_specs["transform"].append(
            {
                "as": "full_date",
                "calculate": f"timeFormat(datum.event_start, '{TIME_FORMAT}')",
            }
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
            if isinstance(child[k], str):
                child[k] = {vega_lite_field_mapping.get(k, "type"): child[k]}
            if isinstance(parent[k], str):
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
