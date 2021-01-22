from bokeh.resources import CDN
from flask import request, session, current_app
from flask_security import login_required

from flexmeasures.ui.views import flexmeasures_ui
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.data.services.resources import get_asset_group_queries, Resource


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
        for skey in [
            k for k in session.keys() if k not in ("_id", "user_id", "csrf_token")
        ]:
            current_app.logger.info(
                "Removing %s:%s from session ... " % (skey, session[skey])
            )
            del session[skey]
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
        bokeh_html_embedded=bokeh_html_embedded,
        show_map=True,
        message=msg,
        asset_groups=map_asset_groups,
        aggregate_groups=aggregate_groups,
    )
