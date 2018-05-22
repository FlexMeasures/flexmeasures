from typing import Optional, Any
from datetime import datetime

from flask import current_app
from bokeh.models import Range1d
from bokeh.plotting import figure, Figure
from bokeh.models import ColumnDataSource, HoverTool, NumeralTickFormatter, BoxAnnotation, CustomJS
from bokeh import events
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


def make_range(series: pd.Series, other_series: pd.Series = None) -> Range1d:
    """Make a 1D range of values from a series or two. Useful to share axis among Bokeh Figures."""
    a_range = None
    if series.size > 0:  # if there is some actual data, use that to set the range
        a_range = Range1d(start=min(series), end=max(series))
    if other_series is not None:  # if there is other data, include it
        a_range = Range1d(start=min(series.append(other_series)),
                          end=max(series.append(other_series)))
    if a_range is None:
        current_app.logger.warn("Not sufficient data to create a range.")
    return a_range


def create_graph(series: pd.Series, title: str="A plot", x_label: str="X", y_label: str="Y", legend: str=None,
                 x_range: Range1d=None, forecasts: pd.DataFrame=None,
                 hover_tool: Optional[HoverTool]=None, show_y_floats: bool=False) -> Figure:
    """
    Create a Bokeh graph. As of now, assumes x data is datetimes and y data is numeric. The former is not set in stone.

    :param series: the actual data
    :param title: Title of the graph
    :param x_label: x axis label
    :param y_label: y axis label
    :param legend: Legend identifier for data series
    :param x_range: values for x axis. If None, taken from series index.
    :param forecasts: forecasts of the data. Expects column names "yhat", "yhat_upper" and "yhat_lower".
    :param hover_tool: Bokeh hover tool, if required
    :param show_y_floats: if True, y axis will show floating numbers (defaults False, will be True if y values are < 2)
    :return: a Bokeh Figure
    """

    if x_range is None:
        x_range = make_range(series.index)

    # set tools
    tools = ["box_zoom", "reset", "save"]
    if hover_tool is not None:
        tools = [hover_tool] + tools

    if show_y_floats is False and series.size > 0:  # apply a simple heuristic
        if forecasts is None:
            show_y_floats = max(series.values) < 2
        else:
            show_y_floats = max(max(series.values), max(forecasts.yhat)) < 2

    fig = figure(title=title,
                 x_range=x_range,
                 min_border=0,
                 toolbar_location="right", tools=tools,
                 h_symmetry=False, v_symmetry=False,
                 sizing_mode='scale_width',
                 outline_line_color="#666666")

    # Make a data source which encodes with each x (start time) also the boundary to which it runs (end time).
    # Useful for the hover tool. TODO: only works with datetime indexes
    x = series.index.values
    if x.size and series.index.freq is not None:  # i.e. if there is data and with a clearly defined frequency
        next_x = pd.DatetimeIndex(start=x[1], freq=series.index.freq, periods=len(series)).values
    else:
        next_x = []
    y = series.values
    data_source = ColumnDataSource(dict(x=x, next_x=next_x, y=y))

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


def highlight(fig: Figure, x_start: Any, x_end: Any, color: str="#FF3936", redirect_to: str=None):
    """Add a box highlight to an area above the x axis.
    If a redirection URL is given, it can open the URL on double-click (this assumes datetimes are used on x axis!).
    It will pass the year, month, day, hour and minute as parameters to the URL."""
    ba = BoxAnnotation(left=x_start, right=x_end,
                       fill_alpha=0.1, line_color=color, fill_color=color)
    fig.add_layout(ba)

    if redirect_to is not None:
        if isinstance(x_start, datetime):
            def open_order_book(o_url: str, box_start: datetime, box_end: datetime) -> CustomJS:
                return CustomJS(code="""
                    var boxStartDate = new Date("%s");
                    var boxEndDate = new Date("%s");
                    var clickedDate = new Date(cb_obj["x"]);
                    // This quickfixes some localisation behaviour in bokehJS (a bug?). Bring it back to UTC.
                    clickedDate = new Date(clickedDate.getTime() + clickedDate.getTimezoneOffset() * 60000);
                    if (boxStartDate <= clickedDate && clickedDate <= boxEndDate) {
                        // TODO: change this to a URL which fits the order book once we actually make it work
                        var urlPlusParams = "%s" + "?year=" + clickedDate.getUTCFullYear()
                                                 + "&month=" + (clickedDate.getUTCMonth()+1)
                                                 + "&day=" + clickedDate.getUTCDate()
                                                 + "&hour=" + clickedDate.getUTCHours()
                                                 + "&minute=" + clickedDate.getMinutes();
                        $(location).attr("href", urlPlusParams);
                    }
                """ % (box_start, box_end, o_url))
        else:
            open_order_book = None  # TODO: implement for other x-range types
        fig.js_on_event(events.DoubleTap, open_order_book(redirect_to, x_start, x_end))
