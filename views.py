from flask import Blueprint, request, session

from bokeh.embed import components
from bokeh.util.string import encode_utf8

from utils import set_period, render_a1vpp_template, get_assets, get_data
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
    data = get_data(session["resource"], session["start_time"], session["end_time"])

    hover = plotting.create_hover_tool()
    fig = plotting.create_asset_graph(data.actual, forecasts=data[["yhat", "yhat_upper", "yhat_lower"]],
                                      title="Load on %s" % session["resource"],
                                      x_label=session["resolution"], y_label="MW",
                                      hover_tool=hover)

    script, div = components(fig)
    return render_a1vpp_template("analytics.html",
                                 load_profile_div=encode_utf8(div),
                                 load_profile_script=script,
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
