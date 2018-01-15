import datetime
import json

from flask import request, render_template, session, current_app
from werkzeug.exceptions import BadRequest
import pandas as pd
from bokeh.resources import CDN
import iso8601

from models import Asset, AssetQuery


# global, lazily loaded asset description
ASSETS = []
# global, lazily loaded data source, will be replaced by DB connection probably
DATA = {}


def get_assets() -> list:
    """Return a list of models.Asset objects"""
    global ASSETS
    if len(ASSETS) == 0:
        with open("data/assets.json", "r") as assets_json:
            dict_assets = json.loads(assets_json.read())
        ASSETS = [Asset(**a) for a in dict_assets]
    return ASSETS


def get_asset_groups() -> dict:
    """We group assets by OR-connected queries"""
    return dict(
        solar=(AssetQuery(attr="resource_type", val="solar"),),
        wind=(AssetQuery(attr="resource_type", val="wind"),),
        renewables=(AssetQuery(attr="resource_type", val="solar"), AssetQuery(attr="resource_type", val="wind")),
        vehicles=(AssetQuery(attr="resource_type", val="ev"),)
    )


def get_assets_by_resource(resource: str) -> list:
    """Gather assets which are identified by this resource name."""
    assets = get_assets()
    asset_groups = get_asset_groups()
    if resource not in asset_groups:
        for asset in assets:
            if asset.name == resource:
                return [asset]
        else:
            raise BadRequest("No asset named '%s' was found." % resource)
    resource_assets = set()
    asset_queries = asset_groups[resource]
    for query in asset_queries:
        for asset in assets:
            if hasattr(asset, query.attr) and getattr(asset, query.attr, None) == query.val:
                resource_assets.add(asset)
    if len(resource_assets) == 0:
        raise BadRequest("No asset or asset group named '%s' was found." % resource)
    return list(resource_assets)


def get_data(resource: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Get data for one or more assets. Here we also decides on a resolution."""
    session["resolution"] = decide_resolution(start, end)
    data = None
    for asset in get_assets_by_resource(resource):
        data_label = "%s_res%s" % (asset.name, session["resolution"])
        global DATA
        if data_label not in DATA:
            current_app.logger.info("Loading %s data from disk ..." % data_label)
            DATA[data_label] = pd.read_pickle("data/pickles/df_%s.pickle" % data_label)
        date_mask = (DATA[data_label].index >= start) & (DATA[data_label].index < end)
        if data is None:
            data = DATA[data_label].loc[date_mask]
        else:
            data = data + DATA[data_label].loc[date_mask]
    return data


def decide_resolution(start: datetime, end: datetime) -> str:
    """Decide on a resolution, given the length of the time period."""
    resolution = "15T"  # default is 15 minute intervals
    period_length = end - start
    if period_length > datetime.timedelta(weeks=16):
        resolution = "1w"                                   # So upon switching from days to weeks, you get at least 16 data points
    elif period_length > datetime.timedelta(days=14):
        resolution = "1d"                                   # So upon switching from hours to days, you get at least 14 data points
    elif period_length > datetime.timedelta(hours=48):
        resolution = "1h"                                   # So upon switching from 15min to hours, you get at least 48 data points
    return resolution


def get_most_recent_quarter() -> datetime:
    now = datetime.datetime.now()
    return now.replace(minute=now.minute - (now.minute % 15), second=0, microsecond=0)


def get_default_start_time():
    return get_most_recent_quarter() - datetime.timedelta(days=1)


def get_default_end_time() -> datetime:
    return get_most_recent_quarter()


def set_period():
    """Set period (start_date and end_date) on session if they are not yet set."""
    if "start_time" in request.values:
        session["start_time"] = iso8601.parse_date(request.values.get("start_time"))
    elif "start_time" not in session:
        session["start_time"] = get_default_start_time()
    if "end_time" in request.values:
        session["end_time"] = iso8601.parse_date(request.values.get("end_time"))
    elif "end_time" not in session:
        session["end_time"] = get_default_end_time()
    # For now, we have to work with the data we have, that means 2015
    session["start_time"] = session["start_time"].replace(year=2015)
    session["end_time"] = session["end_time"].replace(year=2015)

    if session["start_time"] >= session["end_time"]:
        raise BadRequest("Start time %s is not after end time %s." % (session["start_time"], session["end_time"]))


def render_a1vpp_template(html_filename: str, **variables):
    """Render template and add all expected template variables, plus the ones given as **variables."""
    if "start_time" in session:
        variables["start_time"] = session["start_time"]
    else:
        variables["start_time"] = get_default_start_time()
    if "end_time" in session:
        variables["end_time"] = session["end_time"]
    else:
        variables["end_time"] = get_default_end_time()
    variables["page"] = html_filename.replace(".html", "")
    if "show_datepicker" not in variables:
        variables["show_datepicker"] = variables["page"] in ("analytics", "portfolio", "control")
    if "show_map" not in variables:
        variables["show_map"] = variables["page"] == "dashboard"
    if "load_profile_div" in variables:
        variables["contains_plots"] = True
        variables["bokeh_css_resources"] = CDN.render_css()
        variables["bokeh_js_resources"] = CDN.render_js()
    else:
        variables["contains_plots"] = False
    return render_template(html_filename, **variables)
