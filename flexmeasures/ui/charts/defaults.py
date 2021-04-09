from functools import wraps
from typing import Callable, Union

import altair as alt


HEIGHT = 300
WIDTH = 600
REDUCED_HEIGHT = REDUCED_WIDTH = 60
SELECTOR_COLOR = "darkred"
TIME_FORMAT = "%I:%M %p on %A %b %e, %Y"
TIME_TOOLTIP_TITLE = "Time and date"
TIME_TITLE = None
TIME_SELECTION_TOOLTIP = "Click and drag to select a time window"


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
        chart_specs["height"] = HEIGHT
        chart_specs["width"] = WIDTH
        chart_specs["transform"] = [
            {
                "as": "full_date",
                "calculate": f"timeFormat(datum.event_start, '{TIME_FORMAT}')",
            }
        ]
        return chart_specs

    return decorated_chart_specs
