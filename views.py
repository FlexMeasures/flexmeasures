from flask import Blueprint, request, session
import pandas as pd
from bokeh.embed import components
from bokeh.util.string import encode_utf8

from utils import (set_period, render_a1vpp_template, get_assets, get_data, freq_label_to_human_readable_label,
                   mean_absolute_error, mean_absolute_percentage_error, weighted_absolute_percentage_error,
                   resolution_to_hour_factor)
import plotting
import models


# The views in this module can as blueprint be registered with the Flask app (see app.py)
a1_views = Blueprint('a1_views', __name__,  static_folder='public', template_folder='templates')


# Dashboard and main landing page
@a1_views.route('/')
@a1_views.route('/dashboard')
def dashboard_view():
    return render_a1vpp_template('dashboard.html')


# Portfolio view
@a1_views.route('/portfolio', methods=['GET', 'POST'])
def portfolio_view():
    return render_a1vpp_template("portfolio.html")


# Analytics view
@a1_views.route('/analytics', methods=['GET', 'POST'])
def analytics_view():
    set_period()
    if "resource" not in session:
        session["resource"] = "ejj_pv"  # default
    if "resource" in request.form:
        session["resource"] = request.form['resource']

    # loads
    load_data = get_data(session["resource"], session["start_time"], session["end_time"])
    load_hover = plotting.create_hover_tool("Time", "", "Load", "MW")
    load_fig = plotting.create_graph(load_data.y, forecasts=load_data[["yhat", "yhat_upper", "yhat_lower"]],
                                     title="Electricity load on %s" % session["resource"],
                                     x_label="Time (sampled by %s)  "
                                     % freq_label_to_human_readable_label(session["resolution"]),
                                     y_label="Load (in MW)",
                                     hover_tool=load_hover)
    load_script, load_div = components(load_fig)

    load_hour_factor = resolution_to_hour_factor(session["resolution"])

    # prices
    prices_data = get_data("epex_da", session["start_time"], session["end_time"])
    prices_hover = plotting.create_hover_tool("Time", "", "Price", "EUR/MWh")
    prices_fig = plotting.create_graph(prices_data.y,
                                       forecasts=prices_data[["yhat", "yhat_upper", "yhat_lower"]],
                                       title="(Day-ahead) Market Prices",
                                       x_label="Time (sampled by %s)  "
                                       % freq_label_to_human_readable_label(session["resolution"]),
                                       y_label="Prices (in EUR/MWh)",
                                       hover_tool=prices_hover)
    prices_script, prices_div = components(prices_fig)

    # revenues
    revenues_data = pd.Series(load_data.y * prices_data.y * load_hour_factor, index=load_data.index)
    revenues_hover = plotting.create_hover_tool("Time", "", "Revenue", "EUR")
    revenues_fig = plotting.create_graph(revenues_data, forecasts=None,
                                         title="By %s, if sold on DA market" % session["resource"],
                                         x_label="Time (sampled by %s)  "
                                         % freq_label_to_human_readable_label(session["resolution"]),
                                         y_label="Revenues (in EUR)",
                                         hover_tool=revenues_hover)
    revenues_script, revenues_div = components(revenues_fig)

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
                                 revenues_series_div=encode_utf8(revenues_div),
                                 revenues_series_script=revenues_script,
                                 realised_load_in_mwh=realised_load_in_mwh.sum(),
                                 realised_unit_price=prices_data.y.mean(),
                                 realised_revenue=revenues_data.values.sum(),
                                 expected_load_in_mwh=expected_load_in_mwh.sum(),
                                 expected_unit_price=prices_data.yhat.mean(),
                                 mae_load_in_mwh=mae_load_in_mwh,
                                 mae_unit_price=mae_unit_price,
                                 mape_load=mape_load,
                                 mape_unit_price=mape_unit_price,
                                 wape_load=wape_load,
                                 wape_unit_price=wape_unit_price,
                                 assets=get_assets(),
                                 asset_groups=models.asset_groups,
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
