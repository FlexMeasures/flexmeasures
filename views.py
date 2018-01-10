
import datetime

from flask import request, render_template, Blueprint, current_app, g as app_global
from werkzeug.exceptions import BadRequest

from bokeh.embed import components
from bokeh.resources import CDN
from bokeh.util.string import encode_utf8

from utils import set_period, render_a1vpp_template, get_solar_data
import plotting


SOLAR_ASSET = "EJJ PV (MW)"

# The views in this module can as blueprint be registered with the Flask app (see app.py)
a1_views = Blueprint('a1_views', __name__,  static_folder='public', template_folder='templates')


# Dashboard and main landing page
@a1_views.route('/')
@a1_views.route('/dashboard')
def dashboard_view():
    #req_month = request.args.get("month", type=int, default=1)
    #req_day = request.args.get("day", type=int, default=1)
    return render_a1vpp_template('dashboard.html')
                           #month=req_month, day=req_day


# Portfolio view
@a1_views.route('/portfolio', methods=['GET', 'POST'])
def portfolio_view():
    return render_a1vpp_template("portfolio.html")


# Analytics view
@a1_views.route('/analytics', methods=['GET', 'POST'])
def analytics_view():
    set_period()
    data = get_solar_data(SOLAR_ASSET, app_global.start_time, app_global.end_time)

    hover = plotting.create_hover_tool()
    fig = plotting.create_dotted_graph(data, "Solar radiation per day on %s" % SOLAR_ASSET, "15min", "MW", hover)

    script, div = components(fig)
    return render_a1vpp_template("analytics.html", pv_profile_div=encode_utf8(div), pv_profile_script=script)


# Control view
@a1_views.route('/control', methods=['GET', 'POST'])
def control_view():
    return render_a1vpp_template("control.html")


# Upload view
@a1_views.route('/upload')
def upload_view():
    return render_a1vpp_template("upload")



# Test view
@a1_views.route('/test')
def test_view():
    """Used to test UI elements"""
    return render_a1vpp_template("test.html")




@a1_views.route("/<int:month>/<int:day>/")
def chart(month, day):
    try:
        datetime.datetime(year=2015, month=month, day=day)
    except ValueError:
        # TODO: raise this error to the UI
        msg = "Day %d is out of range for month %d" % (day, month)
        current_app.logger.error(msg)
        raise BadRequest(msg)

    data = get_solar_data(SOLAR_ASSET, month, day)

    hover = plotting.create_hover_tool()
    fig = plotting.create_dotted_graph(data, "Solar radiation per day on %s" % SOLAR_ASSET, "15min", "MW", hover)

    script, div = components(fig)
    html = render_a1vpp_template("pv.html", month=month, day=day,
                           the_div=div, the_script=script,
                           js_resources=CDN.render_js(),
                           css_resources=CDN.render_css())
    return encode_utf8(html)
