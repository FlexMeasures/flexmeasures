from inspect import getmembers, isfunction

from . import belief_charts
from .defaults import apply_chart_defaults

belief_charts_mapping = {
    k: apply_chart_defaults(v)
    for k, v in getmembers(belief_charts)
    if isfunction(v) or isinstance(v, dict)
}
