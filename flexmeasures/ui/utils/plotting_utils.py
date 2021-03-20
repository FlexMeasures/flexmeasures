from typing import Any, List, Optional, Tuple, Union
from datetime import datetime, timedelta

from flask import current_app
from colour import Color
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
from bokeh.palettes import brewer as brewer_palette
from bokeh import events
import pandas as pd
import pandas_bokeh
import numpy as np
import timely_beliefs as tb

from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.utils.flexmeasures_inflection import capitalize
from flexmeasures.utils.time_utils import (
    server_now,
    localized_datetime_str,
    tz_index_naively,
)
from flexmeasures.ui.utils.view_utils import set_time_range_for_session


def create_hover_tool(  # noqa: C901
    y_unit: str, resolution: timedelta, as_beliefs: bool = False
) -> HoverTool:
    """Describe behaviour of default tooltips
    (we could also return html for custom tooltips)

    Uses from_py_func, a deprecated function since bokeh==1.1
    https://docs.bokeh.org/en/latest/docs/releases.html?highlight=from_py_func
    """

    def horizon_formatter() -> str:
        horizon = value  # type:ignore  # noqa

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
        tooltips.append(("Description", "@label @belief_horizon{custom}."))
    return HoverTool(
        tooltips=tooltips,
        formatters={
            "x": "datetime",
            "next_x": "datetime",
            "y": "numeral",
            "belief_horizon": custom_horizon_string,
        },
    )


def make_range(
    index: pd.DatetimeIndex, other_index: pd.DatetimeIndex = None
) -> Optional[Range1d]:
    """Make a 1D range of values from a datetime index or two. Useful to share axis among Bokeh Figures."""
    index = tz_index_naively(index)
    other_index = tz_index_naively(other_index)
    a_range = None
    # if there is some actual data, use that to set the range
    if not index.empty:
        a_range = Range1d(start=min(index), end=max(index))
    # if there is other data, include it
    if not index.empty and other_index is not None and not other_index.empty:
        a_range = Range1d(
            start=min(index.append(other_index)), end=max(index.append(other_index))
        )
    if a_range is None:
        current_app.logger.warning("Not sufficient data to create a range.")
    return a_range


def replace_source_with_label(data: pd.DataFrame) -> pd.DataFrame:
    """
    Column "source" is dropped, and column "label" is created.
    The former column should contain DataSource objects,
    while the latter will contain only strings.
    """
    if data is not None:
        # source is in the multindex when we trace sources individually
        if "source" not in data.columns and "source" in data.index.names:
            data.reset_index(level="source", inplace=True)
        if "source" in data.columns:
            data["label"] = data["source"].apply(
                lambda x: capitalize(x.label)
                if isinstance(x, DataSource)
                else str(x).capitalize()
            )
            data.drop("source", axis=1, inplace=True)
    return data


def decide_plot_resolution(
    data: pd.DataFrame,
) -> timedelta:
    """
    Finding out which resolution to use:
    prefer resolution in data, otherwise from session (which is based on the session's time period)
    """
    if isinstance(data, tb.BeliefsDataFrame):
        resolution = data.event_resolution
    elif not data.empty and data.index.freq is not None:
        resolution = pd.to_timedelta(data.index.freq)
    else:
        from flask import session

        if "resolution" not in session:
            set_time_range_for_session()
        resolution = pd.to_timedelta(session["resolution"])
    return resolution


def build_palette() -> Tuple[List[str], str, str]:
    """Choose a color palette, and also single out
    our primary, forecasting and scheduling colors"""
    palette = (
        brewer_palette["Set1"][8].copy() * 15
    )  # 7 colors tiled 15 times supports 105 legend items
    primary_color = "#3B0757"
    palette.insert(0, primary_color)
    palette.pop(4)  # too similar to primary
    forecast_color = "#DDD0B3"
    schedule_color = palette.pop(2)
    return palette, forecast_color, schedule_color


def create_graph(  # noqa: C901
    data: pd.DataFrame,
    unit: str = "Some unit",
    title: str = "A plot",
    x_label: str = "X",
    y_label: str = "Y",
    legend_location: Union[str, Tuple[float, float]] = "top_right",
    legend_labels: Tuple[str, Optional[str], Optional[str]] = (
        "Actual",
        "Forecast",
        "Schedules",
    ),
    x_range: Optional[Range1d] = None,
    forecasts: Optional[pd.DataFrame] = None,
    schedules: Optional[pd.DataFrame] = None,
    show_y_floats: bool = False,
    non_negative_only: bool = False,
    tools: Optional[List[str]] = None,
    sizing_mode: str = "scale_width",
) -> Figure:
    """
    Create a Bokeh graph. As of now, assumes x data is datetimes and y data is numeric. The former is not set in stone.

    :param data: the actual data. Expects column name "event_value" and optional "belief_horizon" and "source" columns.
    :param unit: the (physical) unit of the data
    :param title: Title of the graph
    :param x_label: x axis label
    :param y_label: y axis label
    :param legend_location: location of the legend
    :param legend_labels: labels for the legend items
    :param x_range: values for x axis. If None, taken from series index.
    :param forecasts: forecasts of the data. Expects column names "event_value", "yhat_upper" and "yhat_lower".
    :param schedules: scheduled data. Expects column name "event_value".
    :param hover_tool: Bokeh hover tool, if required
    :param show_y_floats: if True, y axis will show floating numbers (defaults False, will be True if y values are < 2)
    :param non_negative_only: whether or not the data can only be non-negative
    :param tools: some tools for the plot, which defaults to ["box_zoom", "reset", "save"].
    :return: a Bokeh Figure
    """

    # Replace "source" column with "label" column (containing strings)
    data = replace_source_with_label(data)
    forecasts = replace_source_with_label(forecasts)
    schedules = replace_source_with_label(schedules)
    resolution = decide_plot_resolution(data)

    # Set x range
    if x_range is None:
        x_range = make_range(data.index)
        if x_range is None and schedules is not None:
            x_range = make_range(schedules.index)
        if x_range is None and forecasts is not None:
            x_range = make_range(forecasts.index)
    data = tz_index_naively(data)

    # Set default y range in case there is no data from which to derive a range
    y_range = None
    if (
        data["event_value"].isnull().all()
        and (forecasts is None or forecasts["event_value"].isnull().all())
        and (schedules is None or schedules["event_value"].isnull().all())
    ):
        y_range = Range1d(start=0, end=1)

    # Set default tools if none were given
    if tools is None:
        tools = ["box_zoom", "reset", "save"]
    if "belief_horizon" in data.columns and "label" in data.columns:
        hover_tool = create_hover_tool(unit, resolution, as_beliefs=True)
    else:
        hover_tool = create_hover_tool(unit, resolution, as_beliefs=False)
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
        sizing_mode=sizing_mode,
        outline_line_color="#666666",
    )

    if non_negative_only:
        fig.y_range.bounds = (0, None)
        fig.y_range.start = 0

    if data.empty:
        current_app.logger.warning("No data to show for %s" % title)

    # Format y floats
    if (
        not data.empty and show_y_floats is False and data["event_value"].size > 0
    ):  # apply a simple heuristic
        if forecasts is None or forecasts.empty:
            show_y_floats = max(data["event_value"].values) < 2
        else:
            show_y_floats = (
                max(max(data["event_value"].values), max(forecasts["event_value"])) < 2
            )

    palette, forecast_color, schedule_color = build_palette()
    legend_items: List[Tuple] = []

    # Plot power data. Support special case of multiple source labels.
    if not data.empty:
        data_groups = {legend_labels[0]: data}
        is_multiple = "label" in data.columns and len(data["label"].unique()) > 1
        if is_multiple:
            data_groups = {
                label: data.loc[data.label == label] for label in data["label"].unique()
            }
        legend_items = []
        for plot_label, plot_data in data_groups.items():
            ds = make_datasource_from(plot_data, resolution)
            if not is_multiple:
                ac = fig.circle(
                    x="x", y="y", source=ds, color=palette.pop(0), alpha=0.5, size=10
                )
            else:
                ac = fig.line(x="x", y="y", source=ds, color=palette.pop(0))
            legend_items.append((plot_label, [ac]))

    # Plot forecast data
    if forecasts is not None and not forecasts.empty:
        forecasts = tz_index_naively(forecasts)
        if "label" not in forecasts:
            forecasts["label"] = "Forecast from unknown source"
        labels = forecasts["label"].unique()
        for label in labels:
            # forecasts from different data sources
            label_forecasts = forecasts[forecasts["label"] == label]
            fds = make_datasource_from(label_forecasts, resolution)
            fc = fig.circle(x="x", y="y", source=fds, color=forecast_color, size=10)
            fl = fig.line(x="x", y="y", source=fds, color=forecast_color)

            # draw uncertainty range as a two-dimensional patch
            if "yhat_lower" and "yhat_upper" in label_forecasts:
                x_points = np.append(label_forecasts.index, label_forecasts.index[::-1])
                y_points = np.append(
                    label_forecasts.yhat_lower, label_forecasts.yhat_upper[::-1]
                )
                fig.patch(
                    x_points,
                    y_points,
                    color=forecast_color,
                    fill_alpha=0.2,
                    line_width=0.01,
                )
            if legend_labels[1] is None:
                raise TypeError("Legend label must be of type string, not None.")
            if label == labels[0]:
                # only add 1 legend item for forecasts
                legend_items.append((legend_labels[1], [fc, fl]))

    # Plot schedule data. Support special case of multiple source labels.
    if (
        schedules is not None
        and not schedules.empty
        and not schedules["event_value"].isnull().all()
    ):
        schedules = tz_index_naively(schedules)

        legend_label = "" if legend_labels[2] is None else legend_labels[2]
        schedule_groups = {legend_label: schedules}
        if "label" in schedules.columns and len(schedules["label"].unique()) > 1:
            schedule_groups = {
                label: schedules.loc[schedules.label == label]
                for label in schedules["label"].unique()
            }
        for plot_label, plot_data in schedule_groups.items():
            sds = make_datasource_from(plot_data, resolution)
            sl = fig.line(x="x", y="y", source=sds, color=palette.pop(0))

            if plot_label is None:
                raise TypeError("Legend label must be of type string, not None.")
            legend_items.append((plot_label, [sl]))

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


def make_datasource_from(data: pd.DataFrame, resolution: timedelta) -> ColumnDataSource:
    """ Make a bokeh data source, which is for instance useful for the hover tool. """

    # Set column names that our HoverTool can interpret (in case of multiple index levels, use the first one)
    data.index.names = ["x"] + data.index.names[1:]
    data = data.rename(columns={"event_value": "y"})

    # If we have a DatetimeIndex, we encode with each x (start time) also the boundary to which it runs (end time).
    # TODO: can be extended to work with other types
    if (
        data.index.values.size
        and isinstance(data.index, pd.DatetimeIndex)
        and resolution is not None
    ):  # i.e. if there is a non-empty DatetimeIndex and a resolution is given
        data["next_x"] = data.index.shift(1, freq=resolution)
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
                    // This quick-fixes some localisation behaviour in bokeh JS (a bug?). Bring back to UTC.
                    clickedDate = new Date(clickedDate.getTime() + clickedDate.getTimezoneOffset() * 60000);
                    console.log("tapped!!");
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
                    % (
                        box_start.replace(tzinfo=None),
                        box_end.replace(tzinfo=None),
                        o_url,
                    )
                )

        else:
            raise NotImplementedError(
                "Highlighting only works for datetime ranges"
            )  # TODO: implement for other x-range types
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
    Requires bokeh==1.0.2 for solution from https://groups.google.com/a/continuum.io/forum/#!topic/bokeh/BJRhWlnmhWU
    Open feature request to share a legend across plots: https://github.com/bokeh/bokeh/issues/7607
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

    if len(separated_legend.items) > 3:
        orientation = "vertical"

    separated_legend.orientation = orientation

    if orientation == "horizontal":
        separated_legend.spacing = 30
    separated_legend.location = "top_center"

    legend_fig.plot_height = (
        compute_legend_height(original_legend) + original_legend.margin * 2
    )

    return legend_fig


def get_latest_power_as_plot(asset: Asset, small: bool = False) -> Tuple[str, str]:
    """Create a plot of an asset's latest power measurement as an embeddable html string (incl. javascript).
    First returned string is the measurement time, second string is the html string."""

    if current_app.config.get("FLEXMEASURES_MODE", "") == "demo":
        before = server_now().replace(year=2015)
    elif current_app.config.get("FLEXMEASURES_MODE", "") == "play":
        before = None  # type:ignore
    else:
        before = server_now()

    power_query = (
        Power.query.filter(Power.asset == asset)
        .filter(Power.horizon <= timedelta(hours=0))
        .order_by(Power.datetime.desc())
    )
    if before is not None:
        power_query = power_query.filter(
            Power.datetime + asset.event_resolution <= before
        )
    latest_power = power_query.first()
    if latest_power is not None:
        latest_power_value = latest_power.value
        if current_app.config.get("FLEXMEASURES_MODE", "") == "demo":
            latest_power_datetime = latest_power.datetime.replace(
                year=datetime.now().year
            )
        else:
            latest_power_datetime = latest_power.datetime
        latest_measurement_time_str = localized_datetime_str(
            latest_power_datetime + asset.event_resolution
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
    percentage_capacity = latest_power_value / asset.capacity_in_mw
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
        ylabel="Power (%s)" % asset.unit,
        zooming=False,
        show_figure=False,
        hovertool=None,
        legend=None,
        toolbar_location=None,
        figsize=(200, 400) if not small else (100, 100),
        ylim=(0, asset.capacity_in_mw),
        xlim=(-0.5, 0.5),
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
        round(latest_power_value, 3),
        asset.unit,
        round(100 * percentage_capacity),
        latest_measurement_time_str,
    )
    return (
        latest_measurement_time_str,
        """<div data-toggle="tooltip" data-placement="bottom" title="%s">%s</div>"""
        % (hover_tool_str, plot_html_str),
    )
