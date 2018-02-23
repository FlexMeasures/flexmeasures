"""Utilities for views"""
import os
import datetime
from typing import List

from flask import render_template, request, session
from bokeh.resources import CDN

import models
from utils import time_utils


def render_bvp_template(html_filename: str, **variables):
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
    if session_prosumer == "buildings":
        return [a for a in assets if a.asset_type.name == "building"]
    if session_prosumer == "solar":
        return [a for a in assets if a.asset_type.name == "solar"]
    if session_prosumer == "onshore":
        return [a for a in assets if "onshore" in a.name]
    if session_prosumer == "offshore":
        return [a for a in assets if "offshore" in a.name]
    else:
        return assets