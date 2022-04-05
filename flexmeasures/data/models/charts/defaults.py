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
        if "config" not in chart_specs:
            chart_specs["config"] = {}
        if "axis" not in chart_specs["config"]:
            chart_specs["config"]["axis"] = {}
        chart_specs["config"]["axis"] = {
            **chart_specs["config"]["axis"],
            **dict(
                titleFontSize=FONT_SIZE,
                labelFontSize=FONT_SIZE,
            ),
        }
        if "title" in chart_specs:
            if isinstance(chart_specs["title"], str):
                chart_specs["title"] = dict(text=chart_specs["title"])
            chart_specs["title"] = {
                **chart_specs["title"],
                **dict(
                    fontSize=FONT_SIZE,
                ),
            }
        if (
            "color" in chart_specs["encoding"]
            and "legend" in chart_specs["encoding"]["color"]
        ):
            chart_specs["encoding"]["color"]["legend"]["titleFontSize"] = FONT_SIZE
            chart_specs["encoding"]["color"]["legend"]["labelFontSize"] = FONT_SIZE

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
