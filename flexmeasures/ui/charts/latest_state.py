from typing import Tuple
from datetime import datetime

from flask import current_app
from colour import Color
import pandas as pd
import pandas_bokeh
from bokeh.models import BoxAnnotation


from flexmeasures.data.services.time_series import convert_query_window_for_demo
from flexmeasures.utils.time_utils import (
    server_now,
    localized_datetime_str,
)
from flexmeasures.data.models.time_series import Sensor


def get_latest_power_as_plot(sensor: Sensor, small: bool = False) -> Tuple[str, str]:
    """
    Create a plot of a sensor's latest power measurement as an embeddable html string (incl. javascript).
    First returned string is the measurement time, second string is the html string.

    Assumes that the sensor has the "capacity_in_mw" attribute.

    TODO: move to Altair.
    """

    if current_app.config.get("FLEXMEASURES_MODE", "") == "play":
        before = None  # type:ignore
    else:
        before = server_now()
        _, before = convert_query_window_for_demo((before, before))

    latest_power = sensor.latest_state()
    if not latest_power.empty:
        latest_power_value = latest_power["event_value"].values[0]
        if current_app.config.get("FLEXMEASURES_MODE", "") == "demo":
            latest_power_datetime = (
                latest_power.event_ends[0]
                .to_pydatetime()
                .replace(year=datetime.now().year)
            )
        else:
            latest_power_datetime = latest_power.event_ends[0].to_pydatetime()
        latest_measurement_time_str = localized_datetime_str(
            latest_power_datetime + sensor.event_resolution
        )
    else:
        latest_power_value = 0
        latest_measurement_time_str = "time unknown"
    if latest_power_value < 0:
        consumption = True
        latest_power_value *= -1
    else:
        consumption = False
    capacity_in_mw = sensor.get_attribute("capacity_in_mw", latest_power_value)
    data = {
        latest_measurement_time_str if not small else "": [0],
        "Capacity in use": [latest_power_value],
        "Remaining capacity": [capacity_in_mw - latest_power_value],
    }
    percentage_capacity = latest_power_value / capacity_in_mw
    df = pd.DataFrame(data)
    p = df.plot_bokeh(
        kind="bar",
        x=latest_measurement_time_str if not small else "",
        y=["Capacity in use", "Remaining capacity"],
        stacked=True,
        colormap=[
            "%s"
            % Color(
                hue=0.3 * min(1.0, 3 / 2 * percentage_capacity),
                saturation=1,
                luminance=min(0.5, 1 - percentage_capacity * 3 / 4),
            ).get_hex_l(),  # 0% red, 38% yellow, 67% green, >67% darker green
            "#f7ebe7",
        ],
        alpha=0.7,
        title=None,
        xlabel=None,
        ylabel="Power (%s)" % sensor.unit,
        zooming=False,
        show_figure=False,
        hovertool=None,
        legend=None,
        toolbar_location=None,
        figsize=(200, 400) if not small else (100, 100),
        ylim=(0, capacity_in_mw),
        xlim=(-0.5, 0.5),
    )
    p.xgrid.visible = False
    for r in p.renderers:
        try:
            r.glyph.width = 1
        except AttributeError:
            pass
    p.xaxis.ticker = []
    p.add_layout(BoxAnnotation(bottom=0, top=capacity_in_mw, fill_color="#f7ebe7"))
    plot_html_str = pandas_bokeh.embedded_html(p)
    hover_tool_str = "%s at %s %s (%s%% capacity).\nLatest state at %s." % (
        "Consuming"
        if consumption
        else "Running"
        if latest_power_value == 0
        else "Producing",
        round(latest_power_value, 3),
        sensor.unit,
        round(100 * percentage_capacity),
        latest_measurement_time_str,
    )
    return (
        latest_measurement_time_str,
        """<div data-toggle="tooltip" data-placement="bottom" title="%s">%s</div>"""
        % (hover_tool_str, plot_html_str),
    )
