"""This module hosts the views"""

import os
import datetime

from flask import render_template, session
from bokeh.resources import CDN

from utils import time_utils


def render_a1vpp_template(html_filename: str, **variables):
    """Render template and add all expected template variables, plus the ones given as **variables."""
    if os.path.exists("static/documentation/html/index.html"):
        variables["documentation_exists"] = True
    else:
        variables["documentation_exists"] = False
    if "start_time" in session:
        variables["start_time"] = session["start_time"]
    else:
        variables["start_time"] = time_utils.get_default_start_time()
    if "end_time" in session:
        variables["end_time"] = session["end_time"]
    else:
        variables["end_time"] = time_utils.get_default_end_time()
    variables["page"] = html_filename.replace(".html", "")
    if "show_datepicker" not in variables:
        variables["show_datepicker"] = variables["page"] in ("analytics", "portfolio", "control")
    if "load_profile_div" in variables or "portfolio_plot_div" in variables:
        variables["contains_plots"] = True
        variables["bokeh_css_resources"] = CDN.render_css()
        variables["bokeh_js_resources"] = CDN.render_js()
    else:
        variables["contains_plots"] = False
    variables["resolution"] = session.get("resolution", "")
    variables["resolution_human"] = time_utils.freq_label_to_human_readable_label(session.get("resolution", ""))

    # TODO: remove when we stop mocking control.html
    if variables["page"] == "control":
        variables["start_time"] = session["start_time"].replace(hour=4, minute=0, second=0)
        variables["end_time"] = variables["start_time"] + datetime.timedelta(hours=1)

    return render_template(html_filename, **variables)
