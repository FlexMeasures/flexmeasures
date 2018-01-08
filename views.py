
import datetime

from flask import render_template, Blueprint, current_app
from werkzeug.exceptions import BadRequest

from bokeh.embed import components
from bokeh.resources import CDN
from bokeh.util.string import encode_utf8

import utils
import plotting


SOLAR_ASSET = "EJJ PV (MW)"

a1_views = Blueprint('a1_views', __name__,  static_folder='public', template_folder='templates')


@a1_views.route("/<int:month>/<int:day>/")
def chart(month, day):
    try:
        datetime.datetime(year=2015, month=month, day=day)
    except ValueError:
        # TODO: raise this error to the UI
        msg = "Day %d is out of range for month %d" % (day, month)
        current_app.logger.error(msg)
        raise BadRequest(msg)

    data = utils.get_solar_data(SOLAR_ASSET, month, day)
    hover = plotting.create_hover_tool()

    fig = plotting.create_dotted_graph(data, "Solar radiation per day on %s" % SOLAR_ASSET, "15min", "MW", hover)

    script, div = components(fig)
    html = render_template("pv.html", month=month, day=day,
                           all_months=range(1, 13),
                           all_days=range(1, 32),
                           the_div=div, the_script=script,
                           js_resources=CDN.render_js(),
                           css_resources=CDN.render_css())
    return encode_utf8(html)
