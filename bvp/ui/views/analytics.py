from typing import List, Union
from datetime import timedelta

import pandas as pd
from flask import session, current_app
from flask_security import roles_accepted
from bokeh.plotting import Figure
from bokeh.embed import components
from bokeh.util.string import encode_utf8
from bokeh.layouts import gridplot
from bokeh.models import Range1d
from inflection import titleize

from bvp.ui.views import bvp_ui
from bvp.utils import time_utils
from bvp.data.services.resources import get_assets, get_asset_groups, Resource
from bvp.data.queries.analytics import (
    get_power_data,
    get_prices_data,
    get_weather_data,
    get_revenues_costs_data,
)
from bvp.ui.utils.view_utils import render_bvp_template, set_session_resource
from bvp.ui.utils import plotting_utils as plotting


@bvp_ui.route("/analytics", methods=["GET", "POST"])
@roles_accepted("admin", "Prosumer")
def analytics_view():
    """ Analytics view. Here, four plots (consumption/generation, weather, prices and a profit/loss calculation)
    and a table of metrics data are prepared. This view allows to select a resource name, from which a
    models.Resource object can be made. The resource name is kept in the session.
    Based on the resource, plots and table are labelled appropriately.
    """
    time_utils.set_time_range_for_session()
    assets = get_assets()
    asset_groups = get_asset_groups()
    groups_with_assets: List[str] = [
        group for group in asset_groups if asset_groups[group].count() > 0
    ]
    set_session_resource(assets, groups_with_assets)
    session_asset_types = Resource(session["resource"]).unique_asset_type_names

    # This is useful information - we might want to adapt the sign of the data and labels.
    showing_pure_consumption_data = all(
        [a.is_pure_consumer for a in Resource(session["resource"]).assets]
    )
    showing_pure_production_data = all(
        [a.is_pure_producer for a in Resource(session["resource"]).assets]
    )

    # Getting data and calculating metrics for them (not for weather, though)
    metrics = dict()
    power_data, power_forecast_data, metrics = get_power_data(
        showing_pure_consumption_data, metrics
    )
    prices_data, prices_forecast_data, metrics = get_prices_data(metrics)
    weather_data, weather_forecast_data, weather_type, metrics = get_weather_data(
        session_asset_types, metrics
    )
    rev_cost_data, rev_cost_forecast_data, metrics = get_revenues_costs_data(
        power_data, prices_data, power_forecast_data, prices_forecast_data, metrics
    )

    # TODO: get rid of this hack, which we use because we mock 2015 data in static mode
    if current_app.config.get("BVP_MODE", "") == "demo":
        if not power_data.empty:
            power_data = power_data.loc[
                power_data.index
                < time_utils.get_most_recent_quarter().replace(year=2015)
            ]
        if not prices_data.empty:
            prices_data = prices_data.loc[
                prices_data.index
                < time_utils.get_most_recent_quarter().replace(year=2015)
            ]
        if not weather_data.empty:
            weather_data = weather_data.loc[
                weather_data.index
                < time_utils.get_most_recent_quarter().replace(year=2015)
                + timedelta(hours=24)
            ]
        if not rev_cost_data.empty:
            rev_cost_data = rev_cost_data.loc[
                rev_cost_data.index
                < time_utils.get_most_recent_quarter().replace(year=2015)
            ]

    # Set shared x range
    series = time_utils.tz_index_naively(power_data.index)
    shared_x_range = Range1d(
        start=min(series), end=max(series) + pd.to_timedelta(power_data.index.freq)
    )

    # Making figures
    power_fig = make_power_figure(
        power_data, power_forecast_data, showing_pure_consumption_data, shared_x_range
    )
    prices_fig = make_prices_figure(prices_data, prices_forecast_data, shared_x_range)
    weather_fig = make_weather_figure(
        weather_data,
        None,
        shared_x_range,
        weather_type,
        session_asset_types,  # Todo: plot weather forecast data, too
    )
    rev_cost_fig = make_revenues_costs_figure(
        rev_cost_data,
        rev_cost_forecast_data,
        showing_pure_consumption_data,
        shared_x_range,
    )

    analytics_plots_script, analytics_plots_div = components(
        gridplot(
            [power_fig, weather_fig],
            [prices_fig, rev_cost_fig],
            toolbar_options={"logo": None},
            sizing_mode="scale_width",
        )
    )

    return render_bvp_template(
        "views/analytics.html",
        analytics_plots_div=encode_utf8(analytics_plots_div),
        analytics_plots_script=analytics_plots_script,
        metrics=metrics,
        assets=assets,
        asset_groups=list(
            zip(groups_with_assets, [titleize(gwa) for gwa in groups_with_assets])
        ),
        resource=session["resource"],
        resource_display_name=Resource(session["resource"]).display_name,
        asset_types=session_asset_types,
        showing_pure_consumption_data=showing_pure_consumption_data,
        showing_pure_production_data=showing_pure_production_data,
        forecast_horizons=time_utils.forecast_horizons_for(session["resolution"]),
        active_forecast_horizon=session["forecast_horizon"],
    )


def make_power_figure(
    data: pd.DataFrame,
    forecast_data: Union[None, pd.DataFrame],
    showing_pure_consumption_data: bool,
    shared_x_range: Range1d,
) -> Figure:
    """Make a bokeh figure for power consumption or generation"""
    if showing_pure_consumption_data:
        title = (
            "Electricity consumption of %s" % Resource(session["resource"]).display_name
        )
    else:
        title = (
            "Electricity production from %s"
            % Resource(session["resource"]).display_name
        )
    power_hover = plotting.create_hover_tool("MW", session.get("resolution"))

    return plotting.create_graph(
        data,
        legend="Actual",
        forecasts=forecast_data,
        title=title,
        x_range=shared_x_range,
        x_label="Time (sampled by %s)"
        % time_utils.freq_label_to_human_readable_label(session["resolution"]),
        y_label="Power (in MW)",
        show_y_floats=True,
        hover_tool=power_hover,
    )


def make_prices_figure(
    data: pd.DataFrame,
    forecast_data: Union[None, pd.DataFrame],
    shared_x_range: Range1d,
) -> Figure:
    """Make a bokeh figure for price data"""
    price_hover = plotting.create_hover_tool("KRW/MWh", session.get("resolution"))
    return plotting.create_graph(
        data,
        legend="Actual",
        forecasts=forecast_data,
        title="Market prices (day-ahead)",
        x_range=shared_x_range,
        x_label="Time (sampled by %s)"
        % time_utils.freq_label_to_human_readable_label(session["resolution"]),
        y_label="Prices (in KRW/MWh)",
        show_y_floats=True,
        hover_tool=price_hover,
    )


def make_weather_figure(
    data: pd.DataFrame,
    forecast_data: Union[None, pd.DataFrame],
    shared_x_range: Range1d,
    weather_type: str,
    session_asset_types: List[str],
) -> Figure:
    """Make a bokeh figure for weather data"""
    # Todo: plot average temperature/total_radiation/wind_speed for asset groups, and update title accordingly
    # Todo: plot multiple weather data types for asset groups, rather than just the first one in the list like below
    if session_asset_types[0] == "wind":
        weather_axis_label = "Wind speed (in m/s)"
    elif session_asset_types[0] == "solar":
        weather_axis_label = "Total radiation (in kW/m²)"
    else:
        weather_axis_label = "Temperature (in °C)"

    if Resource(session["resource"]).is_unique_asset:
        title = "%s at %s" % (
            titleize(weather_type),
            Resource(session["resource"]).display_name,
        )
    else:
        title = "%s" % titleize(weather_type)
    weather_hover = plotting.create_hover_tool("KRW/MWh", session.get("resolution"))
    return plotting.create_graph(
        data,
        forecasts=forecast_data,
        title=title,
        x_range=shared_x_range,
        x_label="Time (sampled by %s)"
        % time_utils.freq_label_to_human_readable_label(session["resolution"]),
        y_label=weather_axis_label,
        legend=None,
        show_y_floats=True,
        hover_tool=weather_hover,
    )


def make_revenues_costs_figure(
    data: pd.DataFrame,
    forecast_data: pd.DataFrame,
    showing_pure_consumption_data: bool,
    shared_x_range: Range1d,
) -> Figure:
    """Make a bokeh figure for revenues / costs data"""
    if showing_pure_consumption_data:
        rev_cost_str = "Costs"
    else:
        rev_cost_str = "Revenues"
    rev_cost_hover = plotting.create_hover_tool("KRW", session.get("resolution"))

    return plotting.create_graph(
        data,
        legend="Actual",
        forecasts=forecast_data,
        title="%s for %s (on day-ahead market)"
        % (rev_cost_str, Resource(session["resource"]).display_name),
        x_range=shared_x_range,
        x_label="Time (sampled by %s)"
        % time_utils.freq_label_to_human_readable_label(session["resolution"]),
        y_label="%s (in KRW)" % rev_cost_str,
        show_y_floats=True,
        hover_tool=rev_cost_hover,
    )
