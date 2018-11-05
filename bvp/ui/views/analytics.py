from typing import List, Union
from datetime import timedelta

import pandas as pd
from flask import session, current_app
from flask_security import roles_accepted
from bokeh.plotting import Figure
from bokeh.embed import components
from bokeh.util.string import encode_utf8
from bokeh.models import Range1d
from inflection import titleize, humanize

from bvp.ui.views import bvp_ui
from bvp.utils import time_utils
from bvp.data.models.markets import Market
from bvp.data.models.weather import WeatherSensor
from bvp.data.services.resources import (
    get_assets,
    get_asset_groups,
    get_markets,
    get_sensor_types,
    Resource,
)
from bvp.data.services.time_series import ensure_timing_vars_are_set
from bvp.data.queries.analytics import (
    get_power_data,
    get_prices_data,
    get_weather_data,
    get_revenues_costs_data,
)
from bvp.ui.utils.view_utils import (
    render_bvp_template,
    set_session_resource,
    set_session_market,
    set_session_sensor_type,
)
from bvp.ui.utils.plotting_utils import create_graph, separate_legend


@bvp_ui.route("/analytics", methods=["GET", "POST"])
@roles_accepted("admin", "Prosumer")
def analytics_view():
    """ Analytics view. Here, four plots (consumption/generation, weather, prices and a profit/loss calculation)
    and a table of metrics data are prepared. This view allows to select a resource name, from which a
    models.Resource object can be made. The resource name is kept in the session.
    Based on the resource, plots and table are labelled appropriately.
    """
    time_utils.set_time_range_for_session()
    markets = get_markets()
    assets = get_assets()
    asset_groups = get_asset_groups()
    groups_with_assets: List[str] = [
        group for group in asset_groups if asset_groups[group].count() > 0
    ]
    selected_resource = set_session_resource(assets, groups_with_assets)
    selected_market = set_session_market(selected_resource)
    sensor_types = get_sensor_types(selected_resource)
    selected_sensor_type = set_session_sensor_type(sensor_types)
    session_asset_types = Resource(session["resource"]).unique_asset_types

    # This is useful information - we might want to adapt the sign of the data and labels.
    showing_pure_consumption_data = all(
        [a.is_pure_consumer for a in Resource(session["resource"]).assets]
    )
    showing_pure_production_data = all(
        [a.is_pure_producer for a in Resource(session["resource"]).assets]
    )

    # Getting data and calculating metrics for them
    metrics = dict()
    power_data, power_forecast_data, metrics = get_power_data(
        showing_pure_consumption_data, metrics
    )
    prices_data, prices_forecast_data, metrics = get_prices_data(
        metrics, selected_market
    )
    weather_data, weather_forecast_data, weather_type, selected_sensor, metrics = get_weather_data(
        Resource(session["resource"]).assets, metrics, selected_sensor_type
    )
    unit_factor = revenue_unit_factor("MWh", selected_market.unit)
    rev_cost_data, rev_cost_forecast_data, metrics = get_revenues_costs_data(
        power_data,
        prices_data,
        power_forecast_data,
        prices_forecast_data,
        metrics,
        unit_factor,
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
    if not series.empty:
        shared_x_range = Range1d(
            start=min(series), end=max(series) + pd.to_timedelta(power_data.index.freq)
        )
    else:
        query_window, resolution = ensure_timing_vars_are_set((None, None), None)
        shared_x_range = Range1d(
            start=query_window[0], end=query_window[1] + pd.to_timedelta(resolution)
        )

    # Making figures
    tools = ["box_zoom", "reset", "save"]
    power_fig = make_power_figure(
        power_data,
        power_forecast_data,
        showing_pure_consumption_data,
        shared_x_range,
        tools=tools,
    )
    prices_fig = make_prices_figure(
        prices_data, prices_forecast_data, shared_x_range, selected_market, tools=tools
    )
    weather_fig = make_weather_figure(
        weather_data,
        weather_forecast_data,
        shared_x_range,
        selected_sensor,
        tools=tools,
    )
    rev_cost_fig = make_revenues_costs_figure(
        rev_cost_data,
        rev_cost_forecast_data,
        showing_pure_consumption_data,
        shared_x_range,
        selected_market,
        tools=tools,
    )

    # Separate a single legend and remove the others
    legend_fig = separate_legend(power_fig, orientation="horizontal")
    weather_fig.renderers.remove(weather_fig.legend[0])
    prices_fig.renderers.remove(prices_fig.legend[0])
    rev_cost_fig.renderers.remove(rev_cost_fig.legend[0])

    legend_script, legend_div = components(legend_fig)
    analytics_plots_script, analytics_plots_divs = components(
        (power_fig, weather_fig, prices_fig, rev_cost_fig)
    )

    return render_bvp_template(
        "views/analytics.html",
        legend_height=legend_fig.plot_height,
        legend_script=legend_script,
        legend_div=legend_div,
        analytics_plots_divs=[encode_utf8(div) for div in analytics_plots_divs],
        analytics_plots_script=analytics_plots_script,
        metrics=metrics,
        markets=markets,
        sensor_types=sensor_types,
        assets=assets,
        asset_groups=list(
            zip(groups_with_assets, [titleize(gwa) for gwa in groups_with_assets])
        ),
        selected_market=selected_market,
        selected_resource=selected_resource,
        selected_sensor_type=selected_sensor_type,
        selected_sensor=selected_sensor,
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
    tools: List[str] = None,
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

    return create_graph(
        data,
        unit="MW",
        legend_location="top_right",
        forecasts=forecast_data,
        title=title,
        x_range=shared_x_range,
        x_label="Time (resolution of %s)"
        % time_utils.freq_label_to_human_readable_label(session["resolution"]),
        y_label="Power (in MW)",
        show_y_floats=True,
        tools=tools,
    )


def make_prices_figure(
    data: pd.DataFrame,
    forecast_data: Union[None, pd.DataFrame],
    shared_x_range: Range1d,
    selected_market: Market,
    tools: List[str] = None,
) -> Figure:
    """Make a bokeh figure for price data"""
    return create_graph(
        data,
        unit=selected_market.unit,
        legend_location="top_right",
        forecasts=forecast_data,
        title="%s %s prices"
        % (selected_market.display_name, selected_market.market_type.display_name),
        x_range=shared_x_range,
        x_label="Time (resolution of %s)"
        % time_utils.freq_label_to_human_readable_label(session["resolution"]),
        y_label="Prices (in %s)" % selected_market.unit,
        show_y_floats=True,
        tools=tools,
    )


def make_weather_figure(
    data: pd.DataFrame,
    forecast_data: Union[None, pd.DataFrame],
    shared_x_range: Range1d,
    weather_sensor: WeatherSensor,
    tools: List[str] = None,
) -> Figure:
    """Make a bokeh figure for weather data"""
    # Todo: plot average temperature/total_radiation/wind_speed for asset groups, and update title accordingly
    if weather_sensor is None:
        return create_graph(pd.DataFrame())
    unit = weather_sensor.unit
    weather_axis_label = "%s (in %s)" % (
        humanize(weather_sensor.sensor_type.display_name),
        unit,
    )

    if Resource(session["resource"]).is_unique_asset:
        title = "%s at %s" % (
            humanize(weather_sensor.sensor_type.display_name),
            Resource(session["resource"]).display_name,
        )
    else:
        title = "%s" % humanize(weather_sensor.sensor_type.display_name)
    return create_graph(
        data,
        unit=unit,
        forecasts=forecast_data,
        title=title,
        x_range=shared_x_range,
        x_label="Time (resolution of %s)"
        % time_utils.freq_label_to_human_readable_label(session["resolution"]),
        y_label=weather_axis_label,
        legend_location="top_right",
        show_y_floats=True,
        tools=tools,
    )


def make_revenues_costs_figure(
    data: pd.DataFrame,
    forecast_data: pd.DataFrame,
    showing_pure_consumption_data: bool,
    shared_x_range: Range1d,
    selected_market: Market,
    tools: List[str] = None,
) -> Figure:
    """Make a bokeh figure for revenues / costs data"""
    if showing_pure_consumption_data:
        rev_cost_str = "Costs"
    else:
        rev_cost_str = "Revenues"

    return create_graph(
        data,
        unit=selected_market.unit[
            :3
        ],  # First three letters of a price unit give the currency (ISO 4217)
        legend_location="top_right",
        forecasts=forecast_data,
        title="%s for %s (on %s %s)"
        % (
            rev_cost_str,
            Resource(session["resource"]).display_name,
            selected_market.display_name,
            selected_market.market_type.display_name,
        ),
        x_range=shared_x_range,
        x_label="Time (resolution of %s)"
        % time_utils.freq_label_to_human_readable_label(session["resolution"]),
        y_label="%s (in %s)" % (rev_cost_str, selected_market.unit[:3]),
        show_y_floats=True,
        tools=tools,
    )


def revenue_unit_factor(quantity_unit: str, price_unit: str) -> float:
    market_quantity_unit = price_unit[
        4:
    ]  # First three letters of a price unit give the currency (ISO 4217), fourth character is "/"
    if quantity_unit == market_quantity_unit:
        return 1
    elif quantity_unit == "MWh" and price_unit[4:] == "kWh":
        return 1000
    else:
        raise NotImplementedError
