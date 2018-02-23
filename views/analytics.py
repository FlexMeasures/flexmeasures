import pandas as pd
from flask import request, session
from werkzeug.exceptions import BadRequest
from bokeh.embed import components
from bokeh.util.string import encode_utf8
from inflection import titleize

from views import bvp_views
from views.utils import render_bvp_template, check_prosumer_mock, filter_mock_prosumer_assets
from utils import time_utils, calculations
from utils.data_access import get_assets, get_data_for_assets, extract_forecasts, Resource
import models
import plotting


@bvp_views.route('/analytics', methods=['GET', 'POST'])
def analytics_view():
    """ Analytics view. Here, four plots (consumption/generation, weather, prices and a profit/loss calculation)
    and a table of data are prepared. This view allows to select a resource name, from which a models.Resource object
     can be made. The resource name is kept in the session.
     Based on the resource, plots and table are labelled appropriately.
    """
    time_utils.set_time_range_for_session()
    groups_with_assets = [group for group in models.asset_groups if len(Resource(group).assets) > 0]
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
    showing_pure_consumption_data = all([a.is_pure_consumer for a in Resource(session["resource"]).assets])
    showing_pure_production_data = all([a.is_pure_producer for a in Resource(session["resource"]).assets])

    # loads
    load_data = Resource(session["resource"]).get_data()
    if load_data is None or load_data.size == 0:
        raise BadRequest("Not enough data available for resource \"%s\" in the time range %s to %s"
                         % (session["resource"].name, session["start_time"], session["end_time"]))
    if showing_pure_consumption_data:
        load_data *= -1
        title = "Electricity consumption of %s" % titleize(session["resource"])
    else:
        title = "Electricity production from %s" % titleize(session["resource"])
    load_hover = plotting.create_hover_tool("MW", session.get("resolution"))
    load_data_to_show = load_data.loc[load_data.index < time_utils.get_most_recent_quarter().replace(year=2015)]
    load_forecast_data = extract_forecasts(load_data)
    load_fig = plotting.create_graph(load_data_to_show.y,
                                     forecasts=load_forecast_data,
                                     title=title,
                                     x_label="Time (sampled by %s)"
                                     % time_utils.freq_label_to_human_readable_label(session["resolution"]),
                                     y_label="Load (in MW)",
                                     show_y_floats=True,
                                     hover_tool=load_hover)
    load_script, load_div = components(load_fig)

    load_hour_factor = time_utils.resolution_to_hour_factor(session["resolution"])

    # prices
    prices_data = get_data_for_assets(["epex_da"])
    prices_hover = plotting.create_hover_tool("KRW/MWh", session.get("resolution"))
    prices_data_to_show = prices_data.loc[prices_data.index < time_utils.get_most_recent_quarter().replace(year=2015)]
    prices_forecast_data = extract_forecasts(prices_data)
    prices_fig = plotting.create_graph(prices_data_to_show.y,
                                       forecasts=prices_forecast_data,
                                       title="Market prices (day-ahead)",
                                       x_label="Time (sampled by %s)"
                                       % time_utils.freq_label_to_human_readable_label(session["resolution"]),
                                       y_label="Prices (in KRW/MWh)",
                                       hover_tool=prices_hover)
    prices_script, prices_div = components(prices_fig)

    # weather
    session_asset_types = Resource(session["resource"]).unique_asset_type_names
    unique_session_resource = Resource(session["resource"]).is_unique_asset

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
    weather_data_to_show = weather_data.loc[weather_data.index < time_utils.get_most_recent_quarter()
                                            .replace(year=2015)]  # TODO: get this 2015 hack out of here
    weather_forecast_data = None
    weather_fig = plotting.create_graph(weather_data_to_show.y,
                                        forecasts=weather_forecast_data,
                                        title=title,
                                        x_label="Time (sampled by %s)"
                                                % time_utils.freq_label_to_human_readable_label(session["resolution"]),
                                        y_label=weather_axis,
                                        legend=None,
                                        hover_tool=weather_hover)
    weather_script, weather_div = components(weather_fig)

    # metrics
    realised_load_in_mwh = pd.Series(load_data.y * load_hour_factor).values
    expected_load_in_mwh = pd.Series(load_forecast_data.yhat * load_hour_factor).values
    mae_load_in_mwh = calculations.mean_absolute_error(realised_load_in_mwh, expected_load_in_mwh)
    mae_unit_price = calculations.mean_absolute_error(prices_data.y, prices_forecast_data.yhat)
    mape_load = calculations.mean_absolute_percentage_error(realised_load_in_mwh, expected_load_in_mwh)
    mape_unit_price = calculations.mean_absolute_percentage_error(prices_data.y, prices_forecast_data.yhat)
    wape_load = calculations.weighted_absolute_percentage_error(realised_load_in_mwh, expected_load_in_mwh)
    wape_unit_price = calculations.weighted_absolute_percentage_error(prices_data.y, prices_forecast_data.yhat)

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

    # more metrics
    mae_revenues_costs = calculations.mean_absolute_error(rev_cost_data.values, rev_cost_forecasts.yhat)
    mape_revenues_costs = calculations.mean_absolute_percentage_error(rev_cost_data.values, rev_cost_forecasts.yhat)
    wape_revenues_costs = calculations.weighted_absolute_percentage_error(rev_cost_data.values, rev_cost_forecasts.yhat)

    # TODO: get the 2015 hack out of here when we use live data
    rev_costs_data_to_show = \
        rev_cost_data.loc[rev_cost_data.index < time_utils.get_most_recent_quarter().replace(year=2015)]
    rev_cost_fig = plotting.create_graph(rev_costs_data_to_show,
                                         forecasts=rev_cost_forecasts,
                                         title="%s for %s (on day-ahead market)"
                                         % (rev_cost_str, titleize(session["resource"])),
                                         x_label="Time (sampled by %s)"
                                         % time_utils.freq_label_to_human_readable_label(session["resolution"]),
                                         y_label="%s (in KRW)" % rev_cost_str,
                                         hover_tool=rev_cost_hover)
    rev_cost_script, rev_cost_div = components(rev_cost_fig)
    return render_bvp_template("analytics.html",
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
                               expected_revenues_costs=rev_cost_forecasts.yhat.sum(),
                               mae_load_in_mwh=mae_load_in_mwh,
                               mae_unit_price=mae_unit_price,
                               mae_revenues_costs=mae_revenues_costs,
                               mape_load=mape_load,
                               mape_unit_price=mape_unit_price,
                               mape_revenues_costs=mape_revenues_costs,
                               wape_load=wape_load,
                               wape_unit_price=wape_unit_price,
                               wape_revenues_costs=wape_revenues_costs,
                               assets=assets,
                               asset_groups=list(zip(groups_with_assets,
                                                     [titleize(gwa) for gwa in groups_with_assets])),
                               resource=session["resource"],
                               showing_pure_consumption_data=showing_pure_consumption_data,
                               showing_pure_production_data=showing_pure_production_data,
                               prosumer_mock=session.get("prosumer_mock", "0"),
                               forecast_horizons=time_utils.forecast_horizons_for(session["resolution"]),
                               active_forecast_horizon=session["forecast_horizon"])
