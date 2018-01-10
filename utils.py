import datetime

from flask import request, render_template, g
import pandas as pd
from bokeh.resources import CDN
import iso8601


# global data source, will be replaced by DB connection probably
PV_DATA = None


def get_solar_data(solar_asset:str, start:datetime, end:datetime):
    global PV_DATA
    if PV_DATA is None:
        df = pd.read_csv("data/pv.csv")
        df['datetime'] = pd.date_range(start="2015-01-01", end="2015-12-31 23:45:00", freq="15T")
        # TODO: Maybe we actually will want to compute the datetime from the Time column ...
        #df["Seconds_In_2015"] = df.Time * 4 * 15 * 60
        #df['datetime'] = pd.to_datetime(df.Seconds_In_2015, origin=datetime.datetime(year=2015, month=1, day=1), unit="s")
        df = df.set_index('datetime').drop(['Month', 'Day', 'Time'], axis=1)
        PV_DATA = df

    date_range_mask = (PV_DATA.index >= start) & (PV_DATA.index < end)
    return PV_DATA.loc[date_range_mask][solar_asset]


def set_period():
    """Set period (start_date and end_date) on global g if they are not yet set."""
    now = datetime.datetime.now()
    last15minuteTime = now.replace(minute=now.minute - (now.minute % 15), second=0, microsecond=0)
    if not "start_time" in request.values:
        g.start_time = last15minuteTime - datetime.timedelta(days=1)
    else:
        g.start_time = iso8601.parse_date(request.values.get("start_time"))
    if not "end_time" in request.values:
        g.end_time = last15minuteTime
    else:
        g.end_time = iso8601.parse_date(request.values.get("end_time"))
    # For now, we have to work with the data we have, that means 2015
    g.start_time = g.start_time.replace(year=2015)
    g.end_time = g.end_time.replace(year=2015)


def render_a1vpp_template(html_filename, **variables):
    """Render template and add all necessary variables plus the ones given as **variables."""
    set_period()
    variables["start_time"] = g.start_time
    variables["end_time"] = g.end_time
    variables["page"] = html_filename.replace(".html", "")
    print(variables)
    if not "show_map" in variables:
        variables["show_maps"] = variables["page"] == "dashboard"
    if "pv_profile_div" in variables:
        variables["contains_plots"] = True
        variables["bokeh_css_resources"] = CDN.render_css()
        variables["bokeh_js_resources"] = CDN.render_js()
    else:
        variables["contains_plots"] = False
    return render_template(html_filename, **variables)