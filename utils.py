import datetime
import json
from typing import List, Optional

from flask import request, render_template, session, current_app
from werkzeug.exceptions import BadRequest
import pandas as pd
import numpy as np
from bokeh.resources import CDN
import iso8601

from models import Asset, asset_groups, Market


# global, lazily loaded asset description
ASSETS = []
# global, lazily loaded market description
MARKETS = []
# global, lazily loaded data source, will be replaced by DB connection probably
DATA = {}


def get_assets() -> List[Asset]:
    """Return a list of all models.Asset objects. Assets are loaded lazily from file."""
    global ASSETS
    if len(ASSETS) == 0:
        with open("data/assets.json", "r") as assets_json:
            dict_assets = json.loads(assets_json.read())
        ASSETS = [Asset(**a) for a in dict_assets]
    return ASSETS


def get_assets_by_resource(resource: str) -> List[Asset]:
    """Gather assets which are identified by this resource name."""
    assets = get_assets()
    if resource in asset_groups:
        resource_assets = set()
        asset_queries = asset_groups[resource]
        for query in asset_queries:
            for asset in assets:
                if hasattr(asset, query.attr) and getattr(asset, query.attr, None) == query.val:
                    resource_assets.add(asset)
        if len(resource_assets) > 0:
            return list(resource_assets)
    for asset in assets:
        if asset.name == resource:
            return [asset]
    return []


def get_markets() -> List[Market]:
    """Return markets. Markets are loaded lazily from file."""
    global MARKETS
    if len(MARKETS) == 0:
        with open("data/markets.json", "r") as markets_json:
            dict_markets = json.loads(markets_json.read())
        MARKETS = [Market(**a) for a in dict_markets]
    return MARKETS


def get_market_by_resource(resource: str) -> Optional[Market]:
    """Find a market. TODO: support market grouping (see models.market_groups)."""
    markets = get_markets()
    for market in markets:
        if market.name == resource:
            return market


def get_data(resource: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Get data for one or more assets or markets. Here we also decide on a resolution."""
    session["resolution"] = decide_resolution(start, end)
    data = None
    data_keys = []
    for asset in get_assets_by_resource(resource):
        data_keys.append(asset.name)
    market = get_market_by_resource(resource)
    if market is not None:
        data_keys.append(market.name)
    for data_key in data_keys:
        data_label = "%s_res%s" % (data_key, session["resolution"])
        global DATA
        if data_label not in DATA:
            current_app.logger.info("Loading %s data from disk ..." % data_label)
            try:
                DATA[data_label] = pd.read_pickle("data/pickles/df_%s.pickle" % data_label)
            except FileNotFoundError as fnfe:
                raise BadRequest("Sorry, we cannot find any data for the resource \"%s\" ..." % data_key)
        date_mask = (DATA[data_label].index >= start) & (DATA[data_label].index <= end)
        if data is None:
            data = DATA[data_label].loc[date_mask]
        else:
            data = data + DATA[data_label].loc[date_mask]  # assuming grouping means adding up, might differ for markets
    return data


def decide_resolution(start: datetime, end: datetime) -> str:
    """Decide on a resolution, given the length of the time period."""
    resolution = "15T"  # default is 15 minute intervals
    period_length = end - start
    if period_length > datetime.timedelta(weeks=16):
        resolution = "1w"  # So upon switching from days to weeks, you get at least 16 data points
    elif period_length > datetime.timedelta(days=14):
        resolution = "1d"  # So upon switching from hours to days, you get at least 14 data points
    elif period_length > datetime.timedelta(hours=48):
        resolution = "1h"  # So upon switching from 15min to hours, you get at least 48 data points
    return resolution


def resolution_to_hour_factor(resolution: str):
    """Return the factor with which a value needs to be multiplied in order to get the value per hour,
    e.g. 10 MW at a resolution of 15min are 2.5 MWh per time step"""
    switch = {
        "15T": 0.25,
        "1h": 1,
        "1d": 24,
        "1w": 24 * 7
    }
    return switch.get(resolution, 1)


def get_most_recent_quarter() -> datetime:
    now = datetime.datetime.now()
    return now.replace(minute=now.minute - (now.minute % 15), second=0, microsecond=0)


def get_default_start_time() -> datetime:
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


def freq_label_to_human_readable_label(freq_label: str) -> str:
    """Translate pandas frequency labels to human-readable labels."""
    f2h_map = {
        "15T": "15 minutes",
        "1h": "hour",
        "1d": "day",
        "1w": "week"
    }
    return f2h_map.get(freq_label, freq_label)


def mean_absolute_error(y_true, y_forecast):
    y_true, y_forecast = np.array(y_true), np.array(y_forecast)
    return np.mean(np.abs((y_true - y_forecast)))


def mean_absolute_percentage_error(y_true, y_forecast):
    y_true, y_forecast = np.array(y_true), np.array(y_forecast)
    return np.mean(np.abs((y_true - y_forecast) / y_true)) * 100


def weighted_absolute_percentage_error(y_true, y_forecast):
    y_true, y_forecast = np.array(y_true), np.array(y_forecast)
    return np.sum(np.abs((y_true - y_forecast))) / np.sum(y_true) * 100


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
    variables["resolution"] = session.get("resolution", "")
    variables["resolution_human"] = freq_label_to_human_readable_label(session.get("resolution", ""))
    return render_template(html_filename, **variables)
