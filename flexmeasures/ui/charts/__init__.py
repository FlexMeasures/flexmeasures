from inspect import getmembers, isfunction

from . import belief_charts
from .defaults import apply_chart_defaults

# Create a dictionary mapping chart types to chart specs, and apply defaults to the chart specs, too.
# chart types:  Name of a variable defining chart specs or a function returning chart specs.
# chart specs:  A dictionary or Altair chart specification.
#               In case of a dictionary, the creator needs to ensure that the dictionary contains valid vega-lite specs
#               In case of an Altair chart specification, Altair checks for you
belief_charts_mapping = {
    chart_type: apply_chart_defaults(chart_specs)
    for chart_type, chart_specs in getmembers(belief_charts)
    if isfunction(chart_specs) or isinstance(chart_specs, dict)
}
