from typing import Any, List, Optional, Tuple, Union
from datetime import datetime, timedelta

from flask import current_app
from bokeh.plotting import figure, Figure
from bokeh.models import (
    Plot,
    ColumnDataSource,
    HoverTool,
    NumeralTickFormatter,
    BoxAnnotation,
    CustomJS,
    Legend,
    Range1d,
)
from bokeh.models.renderers import GlyphRenderer
from bokeh.models.tools import CustomJSHover
from bokeh import events
import pandas as pd
import pandas_bokeh
import numpy as np

from bvp.data.models.assets import Asset, Power
from bvp.utils.time_utils import localized_datetime_str, tz_index_naively


def create_hover_tool(  # noqa: C901
    y_unit: str, resolution: timedelta, as_beliefs: bool = False
) -> HoverTool:
    """Describe behaviour of default tooltips
    (we could also return html for custom tooltips)"""

    def horizon_formatter() -> str:
        horizon = value  # noqa

        def ngettext(message, plural, num):
            if num == 1:
                return message
            else:
                return plural

        def naturaltime(delta):
            """humanize.naturaldelta adjusted for use in pscript"""

            use_months = False
            seconds = abs(delta // 1000)
            days = seconds // (60 * 60 * 24)
            years = days // 365
            days = days % 365
            months = int(days // 30.5)

            if not years and days < 1:
                if seconds == 0:
                    return "a moment"
                elif seconds == 1:
                    return "a second"
                elif seconds < 60:
                    return ngettext(
                        "%d second" % seconds, "%d seconds" % seconds, seconds
                    )
                elif 60 <= seconds < 120:
                    return "a minute"
                elif 120 <= seconds < 3600:
                    minutes = seconds // 60
                    return ngettext(
                        "%d minute" % minutes, "%d minutes" % minutes, minutes
                    )
                elif 3600 <= seconds < 3600 * 2:
                    return "an hour"
                elif 3600 < seconds:
                    hours = seconds // 3600
                    return ngettext("%d hour" % hours, "%d hours" % hours, hours)
            elif years == 0:
                if days == 1:
                    return "a day"
                if not use_months:
                    return ngettext("%d day" % days, "%d days" % days, days)
                else:
                    if not months:
                        return ngettext("%d day" % days, "%d days" % days, days)
                    elif months == 1:
                        return "a month"
                    else:
                        return ngettext(
                            "%d month" % months, "%d months" % months, months
                        )
            elif years == 1:
                if not months and not days:
                    return "a year"
                elif not months:
                    return ngettext(
                        "1 year, %d day" % days, "1 year, %d days" % days, days
                    )
                elif use_months:
                    if months == 1:
                        return "1 year, 1 month"
                    else:
                        return ngettext(
                            "1 year, %d month" % months,
                            "1 year, %d months" % months,
                            months,
                        )
                else:
                    return ngettext(
                        "1 year, %d day" % days, "1 year, %d days" % days, days
                    )
            else:
                return ngettext("%d year" % years, "%d years" % years, years)

        if isinstance(horizon, list):
            if len(horizon) == 1:
                horizon = horizon[0]
            else:
                min_horizon = min(horizon)
                if min_horizon < 0:
                    return "at most %s after realisation" % naturaltime(min_horizon)
                elif min_horizon > 0:
                    return "at least %s before realisation" % naturaltime(min_horizon)
                else:
                    return "exactly at realisation"
        if horizon < 0:
            return "%s after realisation" % naturaltime(horizon)
        elif horizon > 0:
            return "%s before realisation" % naturaltime(horizon)
        else:
            return "exactly at realisation"

    custom_horizon_string = CustomJSHover.from_py_func(horizon_formatter)
    if resolution.seconds == 0:
        date_format = "@x{%F} to @next_x{%F}"
    else:
        date_format = "@x{%F %H:%M} to @next_x{%F %H:%M}"

    tooltips = [("Time", date_format), ("Value", "@y{0.000a} %s" % y_unit)]
    if as_beliefs:
        tooltips.append(("Description", "@label @horizon{custom}."))
    return HoverTool(
        tooltips=tooltips,
        formatters={
            "x": "datetime",
            "next_x": "datetime",
            "y": "numeral",
            "horizon": custom_horizon_string,
        },
    )


def make_range(
    series: pd.Series, other_series: pd.Series = None
) -> Union[None, Range1d]:
    """Make a 1D range of values from a series or two. Useful to share axis among Bokeh Figures."""
    series = tz_index_naively(series)
    other_series = tz_index_naively(other_series)
    a_range = None
    # if there is some actual data, use that to set the range
    if not series.empty:
        a_range = Range1d(start=min(series), end=max(series))
    # if there is other data, include it
    if not series.empty and other_series is not None and not other_series.empty:
        a_range = Range1d(
            start=min(series.append(other_series)), end=max(series.append(other_series))
        )
    if a_range is None:
        current_app.logger.warn("Not sufficient data to create a range.")
    return a_range


def create_graph(  # noqa: C901
    data: pd.DataFrame,
    unit: str = "Some unit",
    title: str = "A plot",
    x_label: str = "X",
    y_label: str = "Y",
    legend_location: Union[str, Tuple[float, float]] = "top_right",
    legend_labels: Tuple[str, Optional[str]] = ("Actual", "Forecast"),
    x_range: Range1d = None,
    forecasts: pd.DataFrame = None,
    show_y_floats: bool = False,
    non_negative_only: bool = False,
    tools: List[str] = None,
) -> Figure:
    """
    Create a Bokeh graph. As of now, assumes x data is datetimes and y data is numeric. The former is not set in stone.

    :param data: the actual data
    :param unit: the (physical) unit of the data
    :param title: Title of the graph
    :param x_label: x axis label
    :param y_label: y axis label
    :param legend_location: location of the legend
    :param legend_labels: labels for the legend items
    :param x_range: values for x axis. If None, taken from series index.
    :param forecasts: forecasts of the data. Expects column names "yhat", "yhat_upper" and "yhat_lower".
    :param hover_tool: Bokeh hover tool, if required
    :param show_y_floats: if True, y axis will show floating numbers (defaults False, will be True if y values are < 2)
    :param non_negative_only: whether or not the data can only be non-negative
    :param tools: some tools for the plot, which defaults to ["box_zoom", "reset", "save"].
    :return: a Bokeh Figure
    """

    # Make sure even an empty DataFrame has the attributes we need
    if data.empty:
        data["y"] = pd.Series()
        data.index.freq = timedelta()

    # Set x range
    if x_range is None:
        x_range = make_range(data.index)
    data = tz_index_naively(data)

    # Set y range
    y_range = None
    if data.y.isnull().all():
        if forecasts is None:
            y_range = Range1d(start=0, end=1)
        elif forecasts.yhat.isnull().all():
            y_range = Range1d(start=0, end=1)

    # Set default tools if none were given
    if tools is None:
        tools = ["box_zoom", "reset", "save"]
    if "horizon" in data.columns and "label" in data.columns:
        hover_tool = create_hover_tool(
            unit, pd.to_timedelta(data.index.freq), as_beliefs=True
        )
    else:
        hover_tool = create_hover_tool(
            unit, pd.to_timedelta(data.index.freq), as_beliefs=False
        )
    tools = [hover_tool] + tools

    fig = figure(
        title=title,
        x_range=x_range,
        y_range=y_range,
        min_border=0,
        toolbar_location="right",
        tools=tools,
        h_symmetry=False,
        v_symmetry=False,
        sizing_mode="scale_width",
        outline_line_color="#666666",
    )

    if non_negative_only:
        fig.y_range.bounds = (0, None)
        fig.y_range.start = 0

    if data.empty:
        current_app.logger.warn("No data to show for %s" % title)
        print(data)

    # Format y floats
    if show_y_floats is False and data.y.size > 0:  # apply a simple heuristic
        if forecasts is None or forecasts.empty:
            show_y_floats = max(data.y.values) < 2
        else:
            show_y_floats = max(max(data.y.values), max(forecasts.yhat)) < 2

    ds = make_datasource_from(data)
    ac = fig.circle(x="x", y="y", source=ds, color="#3B0757", alpha=0.5, size=10)
    legend_items = [(legend_labels[0], [ac])]

    if forecasts is not None and not forecasts.empty:
        forecasts = tz_index_naively(forecasts)
        fc_color = "#DDD0B3"
        fds = make_datasource_from(forecasts)
        fc = fig.circle(x="x", y="y", source=fds, color=fc_color, size=10)
        fl = fig.line(x="x", y="y", source=fds, color=fc_color)

        # draw uncertainty range as a two-dimensional patch
        if "yhat_lower" and "yhat_upper" in forecasts:
            x_points = np.append(forecasts.index, forecasts.index[::-1])
            y_points = np.append(forecasts.yhat_lower, forecasts.yhat_upper[::-1])
            fig.patch(
                x_points, y_points, color=fc_color, fill_alpha=0.2, line_width=0.01
            )
        if legend_labels[1] is None:
            raise TypeError("Legend label must be of type string, not None.")
        legend_items.append((legend_labels[1], [fc, fl]))

    fig.toolbar.logo = None
    fig.yaxis.axis_label = y_label
    fig.yaxis.formatter = NumeralTickFormatter(format="0,0")
    if show_y_floats:
        fig.yaxis.formatter = NumeralTickFormatter(format="0,0.00")
    fig.ygrid.grid_line_alpha = 0.5
    fig.xaxis.axis_label = x_label
    fig.xgrid.grid_line_alpha = 0.5

    if legend_location is not None:
        legend = Legend(items=legend_items, location=legend_location)
        fig.add_layout(legend, "center")

    return fig


def make_datasource_from(data: pd.DataFrame) -> ColumnDataSource:
    """ Make a bokeh data source, which is for instance useful for the hover tool. """

    # Set column names that our HoverTool can interpret
    data.index.names = ["x"]
    if "y" not in data.columns and "yhat" in data.columns:
        data = data.rename(columns={"yhat": "y"})

    # If we have a DatetimeIndex, we encode with each x (start time) also the boundary to which it runs (end time).
    # TODO: can be extended to work with other types
    if (
        data.index.values.size
        and isinstance(data.index, pd.DatetimeIndex)
        and data.index.freq is not None
    ):  # i.e. if there is a non-empty index with a clearly defined frequency
        data["next_x"] = pd.DatetimeIndex(
            start=data.index.values[1], freq=data.index.freq, periods=len(data.index)
        ).values

    return ColumnDataSource(data)


def highlight(
    fig: Figure,
    x_start: Any,
    x_end: Any,
    color: str = "#FF3936",
    redirect_to: str = None,
):
    """Add a box highlight to an area above the x axis.
    If a redirection URL is given, it can open the URL on double-click (this assumes datetimes are used on x axis!).
    It will pass the year, month, day, hour and minute as parameters to the URL."""
    ba = BoxAnnotation(
        left=x_start, right=x_end, fill_alpha=0.1, line_color=color, fill_color=color
    )
    fig.add_layout(ba)

    if redirect_to is not None:
        if isinstance(x_start, datetime):

            def open_order_book(
                o_url: str, box_start: datetime, box_end: datetime
            ) -> CustomJS:
                return CustomJS(
                    code="""
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
                """
                    % (box_start, box_end, o_url)
                )

        else:
            open_order_book = None  # TODO: implement for other x-range types
        fig.js_on_event(events.DoubleTap, open_order_book(redirect_to, x_start, x_end))


def compute_legend_height(legend) -> float:
    """Adapted from:
    https://github.com/bokeh/bokeh/blob/master/bokehjs/src/lib/models/annotations/legend.ts
    """
    if legend.orientation == "vertical":
        return (
            max(legend.label_height, legend.glyph_height) * len(legend.items)
            + legend.spacing * max(len(legend.items) - 1, 0)
            + legend.padding * 2
        )
    else:
        return max(legend.label_height, legend.glyph_height) + legend.padding * 2


def separate_legend(fig: Figure, orientation: str = "vertical") -> Figure:
    """Cuts legend out of fig and returns a separate legend (as a Figure object).
    Click policy doesn't work on the new legend.
    """

    legend_fig = Plot(
        x_range=Range1d(1000, 1000),
        y_range=Range1d(1000, 1000),
        min_border=0,
        outline_line_alpha=0,
        toolbar_location=None,
        sizing_mode="stretch_both",  # if stretch_both, then we need to set the height or min-height of the container
    )

    original_legend = fig.legend[0]

    legend_fig.renderers.append(original_legend)
    legend_fig.renderers.extend(
        [renderer for renderer in fig.renderers if isinstance(renderer, GlyphRenderer)]
    )

    fig.renderers.remove(original_legend)
    separated_legend = legend_fig.legend[0]
    separated_legend.border_line_alpha = 0
    separated_legend.margin = 0
    separated_legend.orientation = orientation

    if orientation == "horizontal":
        separated_legend.spacing = 30
        separated_legend.location = "top_center"
    else:
        separated_legend.location = "top_left"

    legend_fig.plot_height = (
        compute_legend_height(original_legend) + original_legend.margin * 2
    )

    return legend_fig


def get_latest_power_as_plot(asset: Asset, small: bool = False) -> Tuple[str, str]:
    """Create a plot of an asset's latest power measurement as an embeddable html string (incl. javascript).
    First returned string is the measurement time, second string is the html string."""

    latest_power = (
        Power.query.filter(Power.asset == asset)
        .filter(Power.horizon <= timedelta(hours=0))
        .order_by(Power.datetime.desc())
        .first()
    )
    if latest_power is not None:
        latest_power_value = latest_power.value
        latest_measurement_time_str = localized_datetime_str(
            latest_power.datetime + asset.resolution
        )
    else:
        latest_power_value = 0
        latest_measurement_time_str = "time unknown"
    if latest_power_value < 0:
        consumption = True
        latest_power_value *= -1
    else:
        consumption = False

    data = {
        latest_measurement_time_str if not small else "": [0],
        "Capacity in use": [latest_power_value],
        "Remaining capacity": [asset.capacity_in_mw - latest_power_value],
    }
    df = pd.DataFrame(data)
    p = df.plot_bokeh(
        kind="bar",
        x=latest_measurement_time_str if not small else "",
        y=["Capacity in use", "Remaining capacity"],
        stacked=True,
        colormap=["#c21431", "#f7ebe7"],
        alpha=0.7,
        title=None,
        xlabel=None,
        ylabel="Power (%s)" % asset.unit,
        zooming=False,
        show_figure=False,
        hovertool=None,
        legend=None,
        toolbar_location=None,
        figsize=(200, 400) if not small else (100, 100),
        ylim=(0, asset.capacity_in_mw),
        xlim=(-.5, .5),
    )
    p.xgrid.visible = False
    for r in p.renderers:
        try:
            r.glyph.width = 1
        except AttributeError:
            pass
    p.xaxis.ticker = []
    p.add_layout(
        BoxAnnotation(bottom=0, top=asset.capacity_in_mw, fill_color="#f7ebe7")
    )
    plot_html_str = pandas_bokeh.embedded_html(p)
    hover_tool_str = "%s at %s %s (%s%% capacity).\nLatest state at %s." % (
        "Consuming"
        if consumption
        else "Running"
        if latest_power_value == 0
        else "Producing",
        latest_power_value,
        asset.unit,
        round(100 * latest_power_value / asset.capacity_in_mw),
        latest_measurement_time_str,
    )
    return (
        latest_measurement_time_str,
        """<div data-toggle="tooltip" data-placement="bottom" title="%s">%s</div>"""
        % (hover_tool_str, plot_html_str),
    )
