from flask import request, current_app
from flask_security import login_required
from flask_security.core import current_user
from bokeh.resources import CDN

from flexmeasures.ui.views import flexmeasures_ui
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template, clear_session
from flexmeasures.data.models.generic_assets import get_center_location_of_assets
from flexmeasures.data.services.asset_grouping import (
    AssetGroup,
    get_asset_group_queries,
)


# Dashboard (default root view, see utils/app_utils.py)
@flexmeasures_ui.route("/dashboard")
@login_required
def new_dashboard_view():
    """Dashboard view.
    This is the default landing page.
    It shows a map with the location of all of the assets in the user's account,
    as well as a breakdown of the asset types.
    Here, we are only interested in showing assets with power sensors.
    Admins get to see all assets.

    TODO: Assets for which the platform has identified upcoming balancing opportunities are highlighted.
    """
    msg = ""
    if "clear-session" in request.values:
        clear_session()
        msg = "Your session was cleared."

    aggregate_groups = current_app.config.get("FLEXMEASURES_ASSET_TYPE_GROUPS", {})
    asset_groups = get_asset_group_queries(custom_additional_groups=aggregate_groups)

    map_asset_groups = {}
    for asset_group_name, asset_group_query in asset_groups.items():
        asset_group = AssetGroup(asset_group_name, asset_query=asset_group_query)
        if any(
            [
                a.location and (a.has_power_sensors or a.has_energy_sensors)
                for a in asset_group.assets
            ]
        ):
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
        "views/new_dashboard.html",
        message=msg,
        bokeh_html_embedded=bokeh_html_embedded,
        mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
        map_center=get_center_location_of_assets(user=current_user),
        asset_groups=map_asset_groups,
        aggregate_groups=aggregate_groups,
    )
