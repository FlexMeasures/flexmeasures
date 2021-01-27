from bokeh.resources import CDN
from flask import request, current_app
from flask_security import login_required
from flask_security.core import current_user

from flexmeasures.data.config import db
from flexmeasures.ui.views import flexmeasures_ui
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template, clear_session
from flexmeasures.data.services.resources import (
    get_asset_group_queries,
    Resource,
    get_center_location,
)


# Dashboard and main landing page
@flexmeasures_ui.route("/")
@flexmeasures_ui.route("/dashboard")
@login_required
def dashboard_view():
    """Dashboard view.
    This is the default landing page for the platform user.
    It shows a map with the location and status of all of the user's assets,
    as well as a breakdown of the asset types in the user's portfolio.
    Assets for which the platform has identified upcoming balancing opportunities are highlighted.
    """
    msg = ""
    if "clear-session" in request.values:
        clear_session()
        msg = "Your session was cleared."

    aggregate_groups = ["renewables", "EVSE"]
    asset_groups = get_asset_group_queries(custom_additional_groups=aggregate_groups)
    map_asset_groups = {}
    for asset_group_name in asset_groups:
        asset_group = Resource(asset_group_name)
        map_asset_groups[asset_group_name] = asset_group

    # Pack CDN resources (from pandas_bokeh/base.py)
    bokeh_html_embedded = ""
    for css in CDN.css_files:
        bokeh_html_embedded += (
            """<link href="%s" rel="stylesheet" type="text/css">\n""" % css
        )
    for js in CDN.js_files:
        bokeh_html_embedded += """<script src="%s"></script>\n""" % js

    return render_flexmeasures_template(
        "views/dashboard.html",
        message=msg,
        bokeh_html_embedded=bokeh_html_embedded,
        mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
        map_center=get_center_location(db, user=current_user),
        asset_groups=map_asset_groups,
        aggregate_groups=aggregate_groups,
    )
