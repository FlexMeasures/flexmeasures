from typing import Optional

from bokeh.models import Range1d
from bokeh.plotting import figure
import pandas as pd
import numpy as np


def create_hover_tool() -> Optional[str]:
    """we can return html for hover tooltips"""
    # return HoverTool(tooltips=hover_html)
    return None


def create_asset_graph(series: pd.Series, forecasts: pd.DataFrame = None,
                       title: str="A1 plot", x_label: str="X", y_label: str="Y",
                       hover_tool: str=None):
    xdr = Range1d(start=min(series.index), end=max(series.index))
    ydr = Range1d(start=0, end=max(series)*1.5)

    tools = []
    if hover_tool:
        tools = [hover_tool, ]

    fig = figure(title=title, x_range=xdr, y_range=ydr,
                 min_border=0, toolbar_location="above", tools=tools,
                 h_symmetry=False, v_symmetry=False,
                 sizing_mode='scale_width',
                 outline_line_color="#666666")

    fig.circle(series.index, series.values, color="#3B0757", alpha=0.5, legend="Actual")

    if forecasts is not None:
        fc_color = "#DDD0B3"
        fig.line(series.index, forecasts["yhat"], color=fc_color, legend="Forecast")

        # draw uncertainty range as a two-dimensional patch
        x_points = np.append(series.index, series.index[::-1])
        y_points = np.append(forecasts["yhat_lower"], forecasts["yhat_upper"][::-1])
        fig.patch(x_points, y_points, color=fc_color, fill_alpha=0.2, line_width=0.01)

    fig.toolbar.logo = None
    fig.yaxis.axis_label = y_label
    fig.ygrid.grid_line_alpha = 0.5
    fig.xaxis.axis_label = x_label
    fig.xgrid.grid_line_alpha = 0.5

    return fig
