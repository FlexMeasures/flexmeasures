from typing import List, Tuple, Union
from datetime import timedelta

import pandas as pd
from flask import request, session
from flask_security import roles_accepted
from bokeh.plotting import Figure
from bokeh.embed import components
from bokeh.util.string import encode_utf8
from bokeh.layouts import gridplot
from bokeh.models import Range1d
from inflection import titleize

from views import bvp_views
from models.assets import Asset
from utils.view_utils import render_bvp_template
from utils import time_utils, calculations
from utils.data_access import get_assets, get_asset_groups, get_data_for_assets, extract_forecasts, Resource
from utils import plotting_utils as plotting


@bvp_views.route('/analytics', methods=['GET', 'POST'])
@roles_accepted('admin', 'asset-owner')
def analytics_view():
    """ Analytics view. Here, four plots (consumption/generation, weather, prices and a profit/loss calculation)
    and a table of metrics data are prepared. This view allows to select a resource name, from which a
    models.Resource object can be made. The resource name is kept in the session.
    Based on the resource, plots and table are labelled appropriately.
    """
    time_utils.set_time_range_for_session()
    assets = get_assets()
    asset_groups = get_asset_groups()
    groups_with_assets: List[str] = [group for group in asset_groups if asset_groups[group].count() > 0]
    set_session_resource(assets, groups_with_assets)
    session_asset_types = Resource(session["resource"]).unique_asset_type_names

    # This is useful information - we might want to adapt the sign of the data and labels.
    showing_pure_consumption_data = all([a.is_pure_consumer for a in Resource(session["resource"]).assets])
    showing_pure_production_data = all([a.is_pure_producer for a in Resource(session["resource"]).assets])

    # Getting data and calculating metrics for them (not for weather, though)
    metrics = dict()
    power_data, power_forecast_data, metrics = get_power_data(showing_pure_consumption_data, metrics)
    prices_data, prices_forecast_data, metrics = get_prices_data(metrics)
    weather_data, weather_forecast_data, weather_type, metrics = get_weather_data(session_asset_types, metrics)
    rev_cost_data, rev_cost_forecast_data, metrics = get_revenues_costs_data(power_data, prices_data,
                                                                             power_forecast_data, prices_forecast_data,
                                                                             metrics)

    # TODO: get rid of this hack, which we use because we mock 2015 data
    power_data_to_show = power_data.loc[power_data.index < time_utils.get_most_recent_quarter().replace(year=2015)]
    prices_data_to_show = prices_data.loc[prices_data.index < time_utils.get_most_recent_quarter().replace(year=2015)]
    weather_data_to_show = weather_data.loc[weather_data.index <
                                            time_utils.get_most_recent_quarter().replace(year=2015)
                                            + timedelta(hours=24)]
    rev_cost_data_to_show = \
        rev_cost_data.loc[rev_cost_data.index < time_utils.get_most_recent_quarter().replace(year=2015)]

    # Making figures
    shared_x_range = plotting.make_range(power_data_to_show.index, power_forecast_data.index)
    power_fig = make_power_figure(power_data_to_show.y, power_forecast_data, showing_pure_consumption_data,
                                  shared_x_range)
    prices_fig = make_prices_figure(prices_data_to_show.y, prices_forecast_data, shared_x_range)
    weather_fig = make_weather_figure(weather_data_to_show.y, None, shared_x_range, weather_type, session_asset_types)
    rev_cost_fig = make_revenues_costs_figure(rev_cost_data_to_show, rev_cost_forecast_data,
                                              showing_pure_consumption_data, shared_x_range)

    analytics_plots_script, analytics_plots_div = components(gridplot([power_fig, weather_fig],
                                                                      [prices_fig, rev_cost_fig],
                                                                      toolbar_options={'logo': None},
                                                                      sizing_mode='scale_width'))

    return render_bvp_template("views/analytics.html",
                               analytics_plots_div=encode_utf8(analytics_plots_div),
                               analytics_plots_script=analytics_plots_script,
                               metrics=metrics,
                               assets=assets,
                               asset_groups=list(zip(groups_with_assets,
                                                     [titleize(gwa) for gwa in groups_with_assets])),
                               resource=session["resource"],
                               resource_display_name=Resource(session["resource"]).display_name,
                               asset_types=session_asset_types,
                               showing_pure_consumption_data=showing_pure_consumption_data,
                               showing_pure_production_data=showing_pure_production_data,
                               forecast_horizons=time_utils.forecast_horizons_for(session["resolution"]),
                               active_forecast_horizon=session["forecast_horizon"])


def set_session_resource(assets: List[Asset], groups_with_assets: List[str]):
    """Set session["resource"] to something, based on the available asset groups or the request."""
    if "resource" not in session:  # set some default, if possible
        if "solar" in groups_with_assets:
            session["resource"] = "solar"
        elif "wind" in groups_with_assets:
            session["resource"] = "wind"
        elif "vehicles" in groups_with_assets:
            session["resource"] = "vehicles"
        elif len(assets) > 0:
            session["resource"] = assets[0].name
    if "resource" in request.args:  # [GET] Set by user clicking on a link somewhere (e.g. dashboard)
        session["resource"] = request.args['resource']
    if "resource" in request.form:  # [POST] Set by user in drop-down field. This overwrites GET, as the URL remains.
        session["resource"] = request.form['resource']


def get_power_data(showing_pure_consumption_data: bool, metrics: dict)\
        -> Tuple[pd.DataFrame, Union[None, pd.DataFrame], dict]:
    """Get power data and metrics"""
    power_data = Resource(session["resource"]).get_data()
    power_forecast_data = extract_forecasts(power_data)
    if showing_pure_consumption_data:
        power_data *= -1
    power_hour_factor = time_utils.resolution_to_hour_factor(session["resolution"])
    realised_power_in_mwh = pd.Series(power_data.y * power_hour_factor).values
    expected_power_in_mwh = pd.Series(power_forecast_data.yhat * power_hour_factor).values
    metrics["realised_power_in_mwh"] = realised_power_in_mwh.sum()
    metrics["expected_power_in_mwh"] = expected_power_in_mwh.sum()
    metrics["mae_power_in_mwh"] = calculations.mean_absolute_error(realised_power_in_mwh, expected_power_in_mwh)
    metrics["mape_power"] = calculations.mean_absolute_percentage_error(realised_power_in_mwh, expected_power_in_mwh)
    metrics["wape_power"] = calculations.weighted_absolute_percentage_error(realised_power_in_mwh,
                                                                            expected_power_in_mwh)
    return power_data, power_forecast_data, metrics


def get_prices_data(metrics: dict) -> Tuple[pd.DataFrame, Union[None, pd.DataFrame], dict]:
    """Get price data and metrics"""
    prices_data = get_data_for_assets(["epex_da"])
    prices_forecast_data = extract_forecasts(prices_data)
    metrics["realised_unit_price"] = prices_data.y.mean()
    metrics["expected_unit_price"] = prices_forecast_data.yhat.mean()
    metrics["mae_unit_price"] = calculations.mean_absolute_error(prices_data.y, prices_forecast_data.yhat)
    metrics["mape_unit_price"] = calculations.mean_absolute_percentage_error(prices_data.y, prices_forecast_data.yhat)
    metrics["wape_unit_price"] = calculations.weighted_absolute_percentage_error(prices_data.y,
                                                                                 prices_forecast_data.yhat)
    return prices_data, prices_forecast_data, metrics


def get_weather_data(session_asset_types: List[str], metrics: dict)\
        -> Tuple[pd.DataFrame, Union[None, pd.DataFrame], str, dict]:
    """Get weather data. No metrics yet, as we do not forecast this. It *is* forecast data we get from elsewhere."""
    if session_asset_types[0] == "wind":
        weather_type = "wind_speed"
    elif session_asset_types[0] == "solar":
        weather_type = "total_radiation"
    else:
        weather_type = "temperature"
    weather_data = get_data_for_assets([weather_type],
                                       session["start_time"], session["end_time"], session["resolution"])
    return weather_data, None, weather_type, metrics


def get_revenues_costs_data(power_data: pd.DataFrame, prices_data: pd.DataFrame,
                            power_forecast_data: pd.DataFrame, prices_forecast_data: pd.DataFrame,
                            metrics: dict) -> Tuple[pd.Series, Union[None, pd.DataFrame], dict]:
    """Compute Revenues/costs data. These data are purely derivative from power and prices.
    For forecasts we use the WAPE metrics. Then we calculate metrics on this construct."""
    rev_cost_data = pd.Series(power_data.y * prices_data.y, index=power_data.index)
    rev_cost_forecasts = pd.DataFrame(index=power_data.index, columns=["yhat", "yhat_upper", "yhat_lower"])
    rev_cost_forecasts.yhat = power_forecast_data.yhat * prices_forecast_data.yhat
    # factor for confidence interval - there might be a better heuristic here
    wape_factor_rev_costs = (metrics["wape_power"] / 100. + metrics["wape_unit_price"] / 100.) / 2.
    wape_span_rev_costs = rev_cost_forecasts.yhat * wape_factor_rev_costs
    rev_cost_forecasts.yhat_upper = rev_cost_forecasts.yhat + wape_span_rev_costs
    rev_cost_forecasts.yhat_lower = rev_cost_forecasts.yhat - wape_span_rev_costs
    metrics["realised_revenues_costs"] = rev_cost_data.values.sum()
    metrics["expected_revenues_costs"] = rev_cost_forecasts.yhat.sum()
    metrics["mae_revenues_costs"] = calculations.mean_absolute_error(rev_cost_data.values, rev_cost_forecasts.yhat)
    metrics["mape_revenues_costs"] = calculations.mean_absolute_percentage_error(rev_cost_data.values,
                                                                                 rev_cost_forecasts.yhat)
    metrics["wape_revenues_costs"] = calculations.weighted_absolute_percentage_error(rev_cost_data.values,
                                                                                     rev_cost_forecasts.yhat)
    return rev_cost_data, rev_cost_forecasts, metrics


def make_power_figure(data: pd.Series,
                      forecast_data: Union[None, pd.DataFrame],
                      showing_pure_consumption_data: bool,
                      shared_x_range: Range1d) -> Figure:
    """Make a bokeh figure for power consumption or generation"""
    if showing_pure_consumption_data:
        title = "Electricity consumption of %s" % Resource(session["resource"]).display_name
    else:
        title = "Electricity production from %s" % Resource(session["resource"]).display_name
    power_hover = plotting.create_hover_tool("MW", session.get("resolution"))

    return plotting.create_graph(data,
                                 legend="Actual",
                                 forecasts=forecast_data,
                                 title=title,
                                 x_range=shared_x_range,
                                 x_label="Time (sampled by %s)"
                                 % time_utils.freq_label_to_human_readable_label(session["resolution"]),
                                 y_label="Power (in MW)",
                                 show_y_floats=True,
                                 hover_tool=power_hover)


def make_prices_figure(data: pd.Series,
                       forecast_data: Union[None, pd.DataFrame],
                       shared_x_range: Range1d) -> Figure:
    """Make a bokeh figure for price data"""
    prices_hover = plotting.create_hover_tool("KRW/MWh", session.get("resolution"))
    return plotting.create_graph(data,
                                 legend="Actual",
                                 forecasts=forecast_data,
                                 title="Market prices (day-ahead)",
                                 x_range=shared_x_range,
                                 x_label="Time (sampled by %s)"
                                 % time_utils.freq_label_to_human_readable_label(session["resolution"]),
                                 y_label="Prices (in KRW/MWh)",
                                 hover_tool=prices_hover)


def make_weather_figure(data: pd.Series,
                        forecast_data: Union[None, pd.DataFrame],
                        shared_x_range: Range1d,
                        weather_type: str,
                        session_asset_types: List[str]) -> Figure:
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
        title = "%s at %s" % (titleize(weather_type), Resource(session["resource"]).display_name)
    else:
        title = "%s" % titleize(weather_type)
    weather_hover = plotting.create_hover_tool("KRW/MWh", session.get("resolution"))
    return plotting.create_graph(data,
                                 forecasts=forecast_data,
                                 title=title,
                                 x_range=shared_x_range,
                                 x_label="Time (sampled by %s)"
                                         % time_utils.freq_label_to_human_readable_label(session["resolution"]),
                                 y_label=weather_axis_label,
                                 legend=None,
                                 hover_tool=weather_hover)


def make_revenues_costs_figure(data: pd.Series, forecast_data: pd.DataFrame,
                               showing_pure_consumption_data: bool, shared_x_range: Range1d) -> Figure:
    """Make a bokeh figure for revenues / costs data"""
    if showing_pure_consumption_data:
        rev_cost_str = "Costs"
    else:
        rev_cost_str = "Revenues"
    rev_cost_hover = plotting.create_hover_tool("KRW", session.get("resolution"))

    return plotting.create_graph(data,
                                 legend="Actual",
                                 forecasts=forecast_data,
                                 title="%s for %s (on day-ahead market)"
                                 % (rev_cost_str, Resource(session["resource"]).display_name),
                                 x_range=shared_x_range,
                                 x_label="Time (sampled by %s)"
                                 % time_utils.freq_label_to_human_readable_label(session["resolution"]),
                                 y_label="%s (in KRW)" % rev_cost_str,
                                 hover_tool=rev_cost_hover)
