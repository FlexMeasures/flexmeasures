from flask import Blueprint, request, session
from werkzeug.exceptions import BadRequest
import pandas as pd
from bokeh.embed import components
from bokeh.util.string import encode_utf8

from utils import (set_period, render_a1vpp_template, get_assets, get_data, freq_label_to_human_readable_label,
                   mean_absolute_error, mean_absolute_percentage_error, weighted_absolute_percentage_error,
                   resolution_to_hour_factor, get_assets_by_resource, is_pure_consumer)
import plotting
import models


# The views in this module can as blueprint be registered with the Flask app (see app.py)
a1_views = Blueprint('a1_views', __name__,  static_folder='public', template_folder='templates')


# Dashboard and main landing page
@a1_views.route('/')
@a1_views.route('/dashboard')
def dashboard_view():
    msg = ""
    if "clear-session" in request.values:
        session.clear()
        msg = "Your session was cleared."

    asset_counts = {}
    for asset_type in ("solar", "wind", "vehicles", "house"):
        asset_counts[asset_type] = len(get_assets_by_resource(asset_type))
    return render_a1vpp_template('dashboard.html', message=msg, asset_counts=asset_counts)


# Portfolio view
@a1_views.route('/portfolio', methods=['GET', 'POST'])
def portfolio_view():
    set_period()
    assets = get_assets()
    revenues = dict.fromkeys([a.name for a in assets])
    generation = dict.fromkeys([a.name for a in assets])
    consumption = dict.fromkeys([a.name for a in assets])
    prices_data = get_data("epex_da", session["start_time"], session["end_time"])
    for asset in assets:
        load_data = get_data(asset.name, session["start_time"], session["end_time"])
        revenues[asset.name] = pd.Series(load_data.y * prices_data.y, index=load_data.index).sum()
        if is_pure_consumer(asset.name):
            generation[asset.name] = 0
            consumption[asset.name] = -1 * pd.Series(load_data.y).sum()
        else:
            generation[asset.name] = pd.Series(load_data.y).sum()
            consumption[asset.name] = 0
    return render_a1vpp_template("portfolio.html", assets=assets,
                                 revenues=revenues, generation=generation, consumption=consumption)


# Analytics view
@a1_views.route('/analytics', methods=['GET', 'POST'])
def analytics_view():
    set_period()
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
    if "resource" in request.form:  # set by user
        session["resource"] = request.form['resource']

    # If we show purely consumption assets, we'll want to adapt the sign of the data and labels.
    showing_pure_consumption_data = is_pure_consumer(session["resource"])

    # loads
    load_data = get_data(session["resource"], session["start_time"], session["end_time"])
    if load_data is None or load_data.size == 0:
        raise BadRequest("Not enough data available for resource \"%s\" in the time range %s to %s"
                         % (session["resource"], session["start_time"], session["end_time"]))
    if showing_pure_consumption_data:
        load_data *= -1
    load_hover = plotting.create_hover_tool("MW", session.get("resolution"))
    load_fig = plotting.create_graph(load_data.y, forecasts=load_data[["yhat", "yhat_upper", "yhat_lower"]],
                                     title="Electricity load on %s" % session["resource"],
                                     x_label="Time (sampled by %s)  "
                                     % freq_label_to_human_readable_label(session["resolution"]),
                                     y_label="Load (in MW)",
                                     show_y_floats=True,
                                     hover_tool=load_hover)
    load_script, load_div = components(load_fig)

    load_hour_factor = resolution_to_hour_factor(session["resolution"])

    # prices
    prices_data = get_data("epex_da", session["start_time"], session["end_time"])
    prices_hover = plotting.create_hover_tool("KRW/MWh", session.get("resolution"))
    prices_fig = plotting.create_graph(prices_data.y,
                                       forecasts=prices_data[["yhat", "yhat_upper", "yhat_lower"]],
                                       title="(Day-ahead) Market Prices",
                                       x_label="Time (sampled by %s)  "
                                       % freq_label_to_human_readable_label(session["resolution"]),
                                       y_label="Prices (in KRW/MWh)",
                                       hover_tool=prices_hover)
    prices_script, prices_div = components(prices_fig)

    # revenues/costs
    rev_cost_data = pd.Series(load_data.y * prices_data.y, index=load_data.index)
    rev_cost_str = "Revenues"
    if showing_pure_consumption_data:
        rev_cost_str = "Costs"
    rev_cost_hover = plotting.create_hover_tool("KRW", session.get("resolution"))
    rev_cost_fig = plotting.create_graph(rev_cost_data, forecasts=None,
                                         title="%s for %s (priced on DA market)" % (rev_cost_str, session["resource"]),
                                         x_label="Time (sampled by %s)  "
                                         % freq_label_to_human_readable_label(session["resolution"]),
                                         y_label="%s (in KRW)" % rev_cost_str,
                                         hover_tool=rev_cost_hover)
    rev_cost_script, rev_cost_div = components(rev_cost_fig)

    realised_load_in_mwh = pd.Series(load_data.y * load_hour_factor).values
    expected_load_in_mwh = pd.Series(load_data.yhat * load_hour_factor).values
    mae_load_in_mwh = mean_absolute_error(realised_load_in_mwh, expected_load_in_mwh)
    mae_unit_price = mean_absolute_error(prices_data.y, prices_data.yhat)
    mape_load = mean_absolute_percentage_error(realised_load_in_mwh, expected_load_in_mwh)
    mape_unit_price = mean_absolute_percentage_error(prices_data.y, prices_data.yhat)
    wape_load = weighted_absolute_percentage_error(realised_load_in_mwh, expected_load_in_mwh)
    wape_unit_price = weighted_absolute_percentage_error(prices_data.y, prices_data.yhat)

    return render_a1vpp_template("analytics.html",
                                 load_profile_div=encode_utf8(load_div),
                                 load_profile_script=load_script,
                                 prices_series_div=encode_utf8(prices_div),
                                 prices_series_script=prices_script,
                                 revenues_costs_series_div=encode_utf8(rev_cost_div),
                                 revenues_costs_series_script=rev_cost_script,
                                 realised_load_in_mwh=realised_load_in_mwh.sum(),
                                 realised_unit_price=prices_data.y.mean(),
                                 realised_revenues_costs=rev_cost_data.values.sum(),
                                 expected_load_in_mwh=expected_load_in_mwh.sum(),
                                 expected_unit_price=prices_data.yhat.mean(),
                                 mae_load_in_mwh=mae_load_in_mwh,
                                 mae_unit_price=mae_unit_price,
                                 mape_load=mape_load,
                                 mape_unit_price=mape_unit_price,
                                 wape_load=wape_load,
                                 wape_unit_price=wape_unit_price,
                                 assets=get_assets(),
                                 asset_groups=groups_with_assets,
                                 resource=session["resource"])


# Control view
@a1_views.route('/control', methods=['GET', 'POST'])
def control_view():
    return render_a1vpp_template("control.html")


# Upload view
@a1_views.route('/upload')
def upload_view():
    return render_a1vpp_template("upload.html")


# Test view
@a1_views.route('/test')
def test_view():
    """Used to test UI elements"""
    return render_a1vpp_template("test.html")
