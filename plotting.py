from typing import Optional

from flask import current_app
from bokeh.models import Range1d
from bokeh.plotting import figure, Figure
from bokeh.models import ColumnDataSource, HoverTool, NumeralTickFormatter
import pandas as pd
import numpy as np


def create_hover_tool(y_unit: str, resolution: str) -> HoverTool:
    """Describe behaviour of default tooltips
    (we could also return html for custom tooltips)"""
    date_format = "@x{%F} to @next_x{%F}"
    if resolution in ("15T", "1h"):
        date_format = "@x{%F %H:%M} to @next_x{%F %H:%M}"

    return HoverTool(tooltips=[
        ('Time', date_format),
        ('Value', "@y{0.000a} %s" % y_unit),
    ], formatters={
        "x": "datetime",
        "next_x": "datetime",
        "y": "numeral"
    })


def create_graph(series: pd.Series, forecasts: pd.DataFrame = None,
                 title: str="A1 plot", x_label: str="X", y_label: str="Y", legend="Actual",
                 hover_tool: Optional[HoverTool]=None, show_y_floats: bool=False) -> Figure:
    """
    Create a Bokeh graph.
    :param series: the actual data
    :param forecasts: forecasts of the data (can go further into the future than the series). Expects column names
                      "yhat", "yhat_upper" and "yhat_lower".
    :param title: Title of the graph
    :param x_label: x axis label
    :param y_label: y axis label
    :param legend: Legend identifier for data series
    :param hover_tool: Bokeh hover tool, if required
    :param show_y_floats: if True, y axis will show floating numbers (defaults False, will be True if y values are < 2)
    :return: a Bokeh Figure
    """

    # set the x axis range
    xdr = None
    if series.size > 0:  # if there is some actual data, use that to set the range
        xdr = Range1d(start=min(series.index), end=max(series.index))
    if forecasts is not None:  # if there is some forecast data where no actual data is available, use that
        xdr = Range1d(start=min(series.index.append(forecasts.index)),
                      end=max(series.index.append(forecasts.index)))
    if xdr is None:
        current_app.logger.warn("Not sufficient data to show anything.")

    # set tools
    tools = ["box_zoom", "reset", "save"]
    if hover_tool is not None:
        tools = [hover_tool] + tools

    if show_y_floats is False and series.size > 0:  # apply a simple heuristic
        if forecasts is None:
            show_y_floats = max(series.values) < 2
        else:
            show_y_floats = max(max(series.values), max(forecasts.yhat)) < 2

    x = series.index.values
    if x.size and series.index.freq is not None:  # i.e. if there is data and with a clearly defined frequency
        next_x = pd.DatetimeIndex(start=x[1], freq=series.index.freq, periods=len(series)).values
    else:
        next_x = []
    y = series.values
    data_source = ColumnDataSource(dict(x=x, next_x=next_x, y=y))
    fig = figure(title=title,
                 x_range=xdr,
                 min_border=0,
                 toolbar_location="right", tools=tools,
                 h_symmetry=False, v_symmetry=False,
                 sizing_mode='scale_width',
                 outline_line_color="#666666")

    fig.circle(x='x', y='y', source=data_source, color="#3B0757", alpha=0.5, legend=legend)

    if forecasts is not None:
        fc_color = "#DDD0B3"
        fig.line(forecasts.index, forecasts["yhat"], color=fc_color, legend="Forecast")

        # draw uncertainty range as a two-dimensional patch
        x_points = np.append(forecasts.index, forecasts.index[::-1])
        y_points = np.append(forecasts.yhat_lower, forecasts.yhat_upper[::-1])
        fig.patch(x_points, y_points, color=fc_color, fill_alpha=0.2, line_width=0.01)

    fig.toolbar.logo = None
    fig.yaxis.axis_label = y_label
    fig.yaxis.formatter = NumeralTickFormatter(format="0,0")
    if show_y_floats:
        fig.yaxis.formatter = NumeralTickFormatter(format="0,0.00")
    fig.ygrid.grid_line_alpha = 0.5
    fig.xaxis.axis_label = x_label
    fig.xgrid.grid_line_alpha = 0.5

    return fig
