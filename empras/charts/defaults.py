from functools import wraps
from typing import Callable, Union

import altair as alt


HEIGHT = 300
WIDTH = 600
REDUCED_HEIGHT = REDUCED_WIDTH = 60
SELECTOR_COLOR = "darkred"
TIME_FORMAT = "%I %p on %A %b %e, %Y"
TIME_TOOLTIP_TITLE = "Time and date"
TIME_TITLE = None
TIME_SELECTION_TOOLTIP = "Click and drag to select a time window"
K_TIME_UNIT_STR = "h"
K_TITLE = "Consumption rate"
AGG_DEMAND_TITLE = "Total consumption"


def apply_chart_defaults(fn):
    @wraps(fn)
    def decorated_chart_specs(*args, **kwargs):
        if isinstance(fn, Callable):
            # function that returns a chart specification
            chart_specs: Union[dict, alt.TopLevelMixin] = fn(*args, **kwargs)
        else:
            # not a function, but a direct chart specification
            chart_specs: Union[dict, alt.TopLevelMixin] = fn
        if isinstance(chart_specs, alt.TopLevelMixin):
            chart_specs = chart_specs.to_dict()
            chart_specs.pop("$schema")
        else:
            dataset_name = kwargs.get("dataset_name", None)
            if dataset_name:
                chart_specs["data"] = {"name": dataset_name}
        chart_specs["height"] = HEIGHT
        chart_specs["width"] = WIDTH
        chart_specs["transform"] = [
            {"as": "full_date", "calculate": f"timeFormat(datum.dt, '{TIME_FORMAT}')"}
        ]
        return chart_specs

    return decorated_chart_specs


def determine_k_unit_str(agg_demand_unit: str):
    """For example:
    >>> calculate_k_unit_str("m3")  # m3/h
    >>> calculate_k_unit_str("kWh")  # kW
    """
    k_unit_str = (
        agg_demand_unit.rpartition(K_TIME_UNIT_STR)[0]
        if agg_demand_unit.endswith(K_TIME_UNIT_STR)
        else f"{agg_demand_unit}/{K_TIME_UNIT_STR}"
    )
    return k_unit_str
