from bokeh.models import HoverTool, Plot, Range1d
from bokeh.plotting import figure
#from bokeh.models.sources import ColumnDataSource


def create_hover_tool():
    """we can return html for hover tooltips"""
    # return HoverTool(tooltips=hover_html)
    return None


def create_dotted_graph(series, title, x_label, y_label, hover_tool=None,
                        width=800, height=500):
    #source = ColumnDataSource(series)
    xdr = Range1d(start=min(series.index), end=max(series.index))
    ydr = Range1d(start=0, end=max(series)*1.5)

    tools = []
    if hover_tool:
        tools = [hover_tool,]

    fig = figure(title=title, x_range=xdr, y_range=ydr,
                 min_border=0, toolbar_location="above", tools=tools,
                 #plot_width=width, plot_height=height,
                 h_symmetry=False, v_symmetry=False,
                 sizing_mode='scale_width',
                 outline_line_color="#666666")

    fig.circle(series.index, series.values, color="navy", alpha=0.5)

    fig.toolbar.logo = None
    fig.yaxis.axis_label = y_label
    fig.ygrid.grid_line_alpha = 0.5
    fig.xaxis.axis_label = x_label
    fig.xgrid.grid_line_alpha = 0.5

    return fig
