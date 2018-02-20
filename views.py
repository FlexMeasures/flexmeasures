from typing import List
from datetime import timedelta

from flask import Blueprint, request, session
from werkzeug.exceptions import BadRequest
import pandas as pd
import numpy as np
from inflection import pluralize, titleize
from bokeh.embed import components
from bokeh.util.string import encode_utf8
from bokeh.palettes import brewer

from utils import (set_time_range_for_session, render_a1vpp_template, get_assets,
                   get_data_by_resource, get_data_for_assets, freq_label_to_human_readable_label,
                   mean_absolute_error, mean_absolute_percentage_error,
                   weighted_absolute_percentage_error, resolution_to_hour_factor, get_assets_by_resource,
                   is_pure_consumer, is_pure_producer, forecast_horizons_for, get_most_recent_quarter,
                   get_most_recent_hour, extract_forecasts, get_unique_asset_type_names, is_unique_asset)
import plotting
import models


# The views in this module can as blueprint be registered with the Flask app (see app.py)
a1_views = Blueprint('a1_views', __name__,  static_folder='public', template_folder='templates')


# TODO: replace these mock helpers when we have real auth & user groups
def check_prosumer_mock() -> bool:
    """Return whether we are showing the mocked version for a prosumer.
    Sets this in the session, as well."""
    if "prosumer_mock" in request.values:
        session["prosumer_mock"] = request.values.get("prosumer_mock")
    return session.get("prosumer_mock") != "0"


def filter_mock_prosumer_assets(assets: List[models.Asset]) -> List[models.Asset]:
    """Return a list of assets based on the mock prosumer type in the session."""
    session_prosumer = session.get("prosumer_mock")
    if session_prosumer == "vehicles":
        return [a for a in assets if a.asset_type.name == "charging_station"]
    if session_prosumer == "building":
        return [a for a in assets if a.asset_type.name == "building"]
    if session_prosumer == "solar":
        return [a for a in assets if a.asset_type.name == "solar"]
    if session_prosumer == "onshore":
        return [a for a in assets if "onshore" in a.name]
    if session_prosumer == "offshore":
        return [a for a in assets if "offshore" in a.name]
    else:
        return assets


# Dashboard and main landing page
@a1_views.route('/')
@a1_views.route('/dashboard')
def dashboard_view():
    msg = ""
    if "clear-session" in request.values:
        session.clear()
        msg = "Your session was cleared."

    assets = []
    asset_counts_per_pluralised_type = {}
    current_asset_loads = {}
    is_prosumer_mock = check_prosumer_mock()
    for asset_type in models.asset_types:
        assets_by_pluralised_type = get_assets_by_resource(pluralize(asset_type))
        if is_prosumer_mock:
            assets_by_pluralised_type = filter_mock_prosumer_assets(assets_by_pluralised_type)
        asset_counts_per_pluralised_type[pluralize(asset_type)] = len(assets_by_pluralised_type)
        for asset in assets_by_pluralised_type:
            # TODO: this is temporary
            current_asset_loads[asset.name] =\
                get_data_for_assets([asset.name],
                                    get_most_recent_quarter().replace(year=2015),
                                    get_most_recent_quarter().replace(year=2015) + timedelta(minutes=15),
                                    "15T").y[0]
            assets.append(asset)

    # Todo: switch from this mock-up function for asset counts to a proper implementation of battery assets
    if not is_prosumer_mock:
        asset_counts_per_pluralised_type["batteries"] = asset_counts_per_pluralised_type["solar"]

    return render_a1vpp_template('dashboard.html', show_map=True, message=msg,
                                 assets=assets,
                                 asset_counts_per_pluralised_type=asset_counts_per_pluralised_type,
                                 current_asset_loads=current_asset_loads,
                                 prosumer_mock=session.get("prosumer_mock", "0"))


# Portfolio view
@a1_views.route('/portfolio', methods=['GET', 'POST'])
def portfolio_view():
    set_time_range_for_session()

    assets = get_assets()
    if check_prosumer_mock():
        assets = filter_mock_prosumer_assets(assets)

    # get data for summaries over the selected period
    generation_per_asset = dict.fromkeys([a.name for a in assets])
    consumption_per_asset = dict.fromkeys([a.name for a in assets])
    profit_loss_per_asset = dict.fromkeys([a.name for a in assets])

    asset_types = {}
    generation_per_asset_type = {}
    consumption_per_asset_type = {}
    profit_loss_per_asset_type = {}

    prices_data = get_data_for_assets(["epex_da"])

    load_hour_factor = resolution_to_hour_factor(session["resolution"])

    for asset in assets:
        load_data = get_data_for_assets([asset.name])
        profit_loss_per_asset[asset.name] = pd.Series(load_data.y * load_hour_factor * prices_data.y,
                                                      index=load_data.index).sum()
        if is_pure_consumer(asset.name):
            generation_per_asset[asset.name] = 0
            consumption_per_asset[asset.name] = -1 * pd.Series(load_data.y).sum() * load_hour_factor
        else:
            generation_per_asset[asset.name] = pd.Series(load_data.y).sum() * load_hour_factor
            consumption_per_asset[asset.name] = 0
        neat_asset_type_name = titleize(asset.asset_type_name)
        if neat_asset_type_name not in generation_per_asset_type:
            asset_types[neat_asset_type_name] = asset.asset_type
            generation_per_asset_type[neat_asset_type_name] = 0.
            consumption_per_asset_type[neat_asset_type_name] = 0.
            profit_loss_per_asset_type[neat_asset_type_name] = 0.
        generation_per_asset_type[neat_asset_type_name] += generation_per_asset[asset.name]
        consumption_per_asset_type[neat_asset_type_name] += consumption_per_asset[asset.name]
        profit_loss_per_asset_type[neat_asset_type_name] += profit_loss_per_asset[asset.name]

    # get data for stacked plot for the selected period

    def only_positive(df: pd.DataFrame) -> None:
        df[df.fillna(0) < 0] = 0

    def only_negative_abs(df: pd.DataFrame) -> None:
        # If this functions fails, a possible solution may be to stack the dataframe before
        # checking for negative values (unstacking afterwards).
        # df = df.stack()
        df[df > 0] = 0
        # df = df.unstack()
        df[:] = df * -1

    def data_or_zeroes(df: pd.DataFrame) -> pd.DataFrame:
        if df is None:
            return pd.DataFrame(index=pd.date_range(start=session["start_time"], end=session["end_time"],
                                                    freq=session["resolution"]),
                                columns=["y"]).fillna(0)
        else:
            return df

    def stacked(df: pd.DataFrame) -> pd.DataFrame:
        """Stack columns of df cumulatively, include bottom"""
        df_top = df.cumsum(axis=1)
        df_bottom = df_top.shift(axis=1).fillna(0)[::-1]
        df_stack = pd.concat([df_bottom, df_top], ignore_index=True)
        return df_stack

    show_stacked = request.values.get("show_stacked", "production")
    if show_stacked == "production":
        show_summed = "consumption"
        stack_types = [t.name for t in asset_types.values() if t.is_producer is True]
        sum_assets = [a.name for a in assets if a.asset_type.is_consumer is True]
        plot_label = "Stacked Generation vs aggregated Consumption"
        stacked_value_mask = only_positive
        summed_value_mask = only_negative_abs
    else:
        show_summed = "production"
        stack_types = [t.name for t in asset_types.values() if t.is_consumer is True]
        sum_assets = [a.name for a in assets if a.asset_type.is_producer is True]
        plot_label = "Stacked Consumption vs aggregated Generation"
        stacked_value_mask = only_negative_abs
        summed_value_mask = only_positive

    df_sum = get_data_for_assets(sum_assets)
    if df_sum is not None:
        df_sum = df_sum.loc[:, ['y']]  # only get the y data
    df_sum = data_or_zeroes(df_sum)
    summed_value_mask(df_sum)
    hover = plotting.create_hover_tool("MW", session.get("resolution"))
    fig = plotting.create_graph(df_sum.y,
                                title=plot_label,
                                x_label="Time (sampled by %s)"
                                        % freq_label_to_human_readable_label(session["resolution"]),
                                y_label="%s (in MW)" % plot_label,
                                legend=show_summed,
                                hover_tool=hover)
    fig.plot_height = 450
    fig.plot_width = 750
    fig.sizing_mode = "fixed"

    df_stacked_data = pd.DataFrame(index=df_sum.index, columns=stack_types)
    for st in stack_types:
        df_stacked_data[st] = get_data_by_resource(pluralize(st)).loc[:, ['y']]  # only get the y data
    stacked_value_mask(df_stacked_data)
    df_stacked_data = data_or_zeroes(df_stacked_data)
    df_stacked_areas = stacked(df_stacked_data)

    num_areas = df_stacked_areas.shape[1]
    if num_areas <= 2:
        colors = ['#99d594', '#dddd9d']
    else:
        colors = brewer['Spectral'][num_areas]
    x_points = np.hstack((df_stacked_data.index[::-1], df_stacked_data.index))

    fig.grid.minor_grid_line_color = '#eeeeee'

    #fig.patches([x2] * df_stacked_areas.shape[1], [df_stacked_areas[c].values for c in df_stacked_areas],
    #            color=colors, alpha=0.8, line_color=None, legend="stack")
    for a, area in enumerate(df_stacked_areas):
        fig.patch(x_points, df_stacked_areas[area].values,
                  color=colors[a], alpha=0.8, line_color=None, legend=titleize(df_stacked_data.columns[a]))

    portfolio_plot_script, portfolio_plot_div = components(fig)

    return render_a1vpp_template("portfolio.html", prosumer_mock=session.get("prosumer_mock", "0"),
                                 assets=assets,
                                 asset_types=asset_types,
                                 generation_per_asset=generation_per_asset,
                                 consumption_per_asset=consumption_per_asset,
                                 profit_loss_per_asset=profit_loss_per_asset,
                                 generation_per_asset_type=generation_per_asset_type,
                                 consumption_per_asset_type=consumption_per_asset_type,
                                 profit_loss_per_asset_type=profit_loss_per_asset_type,
                                 sum_generation=sum(generation_per_asset_type.values()),
                                 sum_consumption=sum(consumption_per_asset_type.values()),
                                 sum_profit_loss=sum(profit_loss_per_asset_type.values()),
                                 portfolio_plot_script=portfolio_plot_script,
                                 portfolio_plot_div=portfolio_plot_div,
                                 alt_stacking=show_summed)


# Analytics view
@a1_views.route('/analytics', methods=['GET', 'POST'])
def analytics_view():
    set_time_range_for_session()
    groups_with_assets = [group for group in models.asset_groups if len(get_assets_by_resource(group)) > 0]
    if "resource" not in session:  # set some default, if possible
        if "solar" in groups_with_assets:
            session["resource"] = "solar"
        elif "wind" in groups_with_assets:
            session["resource"] = "wind"
        elif "vehicles" in groups_with_assets:
            session["resource"] = "vehicles"
        elif len(get_assets()) > 0:
            session["resource"] = get_assets()[0].name
    if "resource" in request.values:  # set by user
        session["resource"] = request.values['resource']

    assets = get_assets()
    if check_prosumer_mock():
        groups_with_assets = []
        assets = filter_mock_prosumer_assets(assets)
        if len(assets) > 0:
            if session.get("prosumer_mock", "0") not in ("0", "offshore", "onshore"):
                groups_with_assets = [session.get("prosumer_mock")]
            if session.get("resource") not in [a.name for a in assets]\
                    and session.get("resource") != session.get("prosumer_mock"):
                session["resource"] = assets[0].name

    # This is useful information - we might want to adapt the sign of the data and labels.
    showing_pure_consumption_data = is_pure_consumer(session["resource"])
    showing_pure_generation_data = is_pure_producer(session["resource"])

    # loads
    load_data = get_data_by_resource(session["resource"])
    if load_data is None or load_data.size == 0:
        raise BadRequest("Not enough data available for resource \"%s\" in the time range %s to %s"
                         % (session["resource"], session["start_time"], session["end_time"]))
    if showing_pure_consumption_data:
        load_data *= -1
        title = "Electricity consumption of %s" % titleize(session["resource"])
    else:
        title = "Electricity production from %s" % titleize(session["resource"])
    load_hover = plotting.create_hover_tool("MW", session.get("resolution"))
    load_data_to_show = load_data.loc[load_data.index < get_most_recent_quarter().replace(year=2015)]
    load_forecast_data = extract_forecasts(load_data)
    load_fig = plotting.create_graph(load_data_to_show.y,
                                     forecasts=load_forecast_data,
                                     title=title,
                                     x_label="Time (sampled by %s)"
                                     % freq_label_to_human_readable_label(session["resolution"]),
                                     y_label="Load (in MW)",
                                     show_y_floats=True,
                                     hover_tool=load_hover)
    load_script, load_div = components(load_fig)

    load_hour_factor = resolution_to_hour_factor(session["resolution"])

    # prices
    prices_data = get_data_for_assets(["epex_da"])
    prices_hover = plotting.create_hover_tool("KRW/MWh", session.get("resolution"))
    prices_data_to_show = prices_data.loc[prices_data.index < get_most_recent_quarter().replace(year=2015)]
    prices_forecast_data = extract_forecasts(prices_data)
    prices_fig = plotting.create_graph(prices_data_to_show.y,
                                       forecasts=prices_forecast_data,
                                       title="Market prices (day-ahead)",
                                       x_label="Time (sampled by %s)"
                                       % freq_label_to_human_readable_label(session["resolution"]),
                                       y_label="Prices (in KRW/MWh)",
                                       hover_tool=prices_hover)
    prices_script, prices_div = components(prices_fig)

    # weather
    session_asset_types = get_unique_asset_type_names(session["resource"])
    unique_session_resource = is_unique_asset(session["resource"])

    # Todo: plot average temperature/total_radiation/wind_speed for asset groups, and update title accordingly
    # Todo: plot multiple weather data types for asset groups, rather than just the first one in the list like below
    if session_asset_types[0] == "wind":
        weather_type = "wind_speed"
        weather_axis = "Wind speed (in m/s)"
    elif session_asset_types[0] == "solar":
        weather_type = "total_radiation"
        weather_axis = "Total radiation (in kW/m²)"
    else:
        weather_type = "temperature"
        weather_axis = "Temperature (in °C)"

    if unique_session_resource:
        title = "%s at %s" % (titleize(weather_type), titleize(session["resource"]))
    else:
        title = "%s" % titleize(weather_type)
    weather_data = get_data_for_assets([weather_type],
                                       session["start_time"], session["end_time"], session["resolution"])
    weather_hover = plotting.create_hover_tool("KRW/MWh", session.get("resolution"))
    weather_data_to_show = weather_data.loc[weather_data.index < get_most_recent_quarter().replace(year=2015)]
    weather_forecast_data = None
    weather_fig = plotting.create_graph(weather_data_to_show.y,
                                       forecasts=weather_forecast_data,
                                       title=title,
                                       x_label="Time (sampled by %s)"
                                               % freq_label_to_human_readable_label(session["resolution"]),
                                       y_label=weather_axis,
                                       legend=None,
                                       hover_tool=weather_hover)
    weather_script, weather_div = components(weather_fig)

    # metrics
    realised_load_in_mwh = pd.Series(load_data.y * load_hour_factor).values
    expected_load_in_mwh = pd.Series(load_forecast_data.yhat * load_hour_factor).values
    mae_load_in_mwh = mean_absolute_error(realised_load_in_mwh, expected_load_in_mwh)
    mae_unit_price = mean_absolute_error(prices_data.y, prices_forecast_data.yhat)
    mape_load = mean_absolute_percentage_error(realised_load_in_mwh, expected_load_in_mwh)
    mape_unit_price = mean_absolute_percentage_error(prices_data.y, prices_forecast_data.yhat)
    wape_load = weighted_absolute_percentage_error(realised_load_in_mwh, expected_load_in_mwh)
    wape_unit_price = weighted_absolute_percentage_error(prices_data.y, prices_forecast_data.yhat)

    # revenues/costs
    rev_cost_data = pd.Series(load_data.y * prices_data.y, index=load_data.index)
    rev_cost_forecasts = pd.DataFrame(index=load_data.index, columns=["yhat", "yhat_upper", "yhat_lower"])
    wape_factor_rev_costs = (wape_load / 100. + wape_unit_price / 100.) / 2.  # there might be a better heuristic here
    rev_cost_forecasts.yhat = load_forecast_data.yhat * prices_forecast_data.yhat
    wape_span_rev_costs = rev_cost_forecasts.yhat * wape_factor_rev_costs
    rev_cost_forecasts.yhat_upper = rev_cost_forecasts.yhat + wape_span_rev_costs
    rev_cost_forecasts.yhat_lower = rev_cost_forecasts.yhat - wape_span_rev_costs
    if showing_pure_consumption_data:
        rev_cost_str = "Costs"
    else:
        rev_cost_str = "Revenues"
    rev_cost_hover = plotting.create_hover_tool("KRW", session.get("resolution"))
    # TODO: get the 2015 hack out of here when we use live data
    rev_costs_data_to_show = rev_cost_data.loc[rev_cost_data.index < get_most_recent_quarter().replace(year=2015)]
    rev_cost_fig = plotting.create_graph(rev_costs_data_to_show,
                                         forecasts=rev_cost_forecasts,
                                         title="%s for %s (on day-ahead market)"
                                         % (rev_cost_str, titleize(session["resource"])),
                                         x_label="Time (sampled by %s)"
                                         % freq_label_to_human_readable_label(session["resolution"]),
                                         y_label="%s (in KRW)" % rev_cost_str,
                                         hover_tool=rev_cost_hover)
    rev_cost_script, rev_cost_div = components(rev_cost_fig)
    return render_a1vpp_template("analytics.html",
                                 load_profile_div=encode_utf8(load_div),
                                 load_profile_script=load_script,
                                 prices_series_div=encode_utf8(prices_div),
                                 prices_series_script=prices_script,
                                 weather_profile_div=encode_utf8(weather_div),
                                 weather_profile_script=weather_script,
                                 revenues_costs_series_div=encode_utf8(rev_cost_div),
                                 revenues_costs_series_script=rev_cost_script,
                                 realised_load_in_mwh=realised_load_in_mwh.sum(),
                                 realised_unit_price=prices_data.y.mean(),
                                 realised_revenues_costs=rev_cost_data.values.sum(),
                                 expected_load_in_mwh=expected_load_in_mwh.sum(),
                                 expected_unit_price=prices_forecast_data.yhat.mean(),
                                 mae_load_in_mwh=mae_load_in_mwh,
                                 mae_unit_price=mae_unit_price,
                                 mape_load=mape_load,
                                 mape_unit_price=mape_unit_price,
                                 wape_load=wape_load,
                                 wape_unit_price=wape_unit_price,
                                 assets=assets,
                                 asset_groups=list(zip(groups_with_assets,
                                                       [titleize(gwa) for gwa in groups_with_assets])),
                                 resource=session["resource"],
                                 showing_pure_consumption_data=showing_pure_consumption_data,
                                 showing_pure_generation_data=showing_pure_generation_data,
                                 prosumer_mock=session.get("prosumer_mock", "0"),
                                 forecast_horizons=forecast_horizons_for(session["resolution"]),
                                 active_forecast_horizon=session["forecast_horizon"])


# Control view
@a1_views.route('/control', methods=['GET', 'POST'])
def control_view():
    check_prosumer_mock()
    return render_a1vpp_template("control.html",
                                 prosumer_mock=session.get("prosumer_mock", "0"))


# Upload view
@a1_views.route('/upload')
def upload_view():
    return render_a1vpp_template("upload.html")


# Test view
@a1_views.route('/test')
def test_view():
    """Used to test UI elements"""
    return render_a1vpp_template("test.html")
