from inspect import getmembers, isfunction

from . import belief_charts
from .defaults import apply_chart_defaults


def chart_type_to_chart_specs(chart_type: str, **kwargs) -> dict:
    """Create chart specs of a given chart type, using FlexMeasures defaults for settings like width and height.

    :param chart_type:  Name of a variable defining chart specs or a function returning chart specs.
                        The chart specs can be a dictionary or an Altair chart specification.
                        - In case of a dictionary, the creator needs to ensure that the dictionary contains valid specs
                        - In case of an Altair chart specification, Altair validates for you
    :returns:           A dictionary containing a vega-lite chart specification
    """
    # Create a dictionary mapping chart types to chart specs, and apply defaults to the chart specs, too.
    belief_charts_mapping = {
        chart_type: apply_chart_defaults(chart_specs)
        for chart_type, chart_specs in getmembers(belief_charts)
        if isfunction(chart_specs) or isinstance(chart_specs, dict)
    }
    # Create chart specs
    chart_specs_or_fnc = belief_charts_mapping[chart_type]
    if isfunction(chart_specs_or_fnc):
        return chart_specs_or_fnc(**kwargs)
    return chart_specs_or_fnc
