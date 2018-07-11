from datetime import timedelta

from flask import request, session, current_app
from flask_security import login_required
from flask_security.core import current_user
from inflection import pluralize

from bvp.ui.views import bvp_ui
from bvp.ui.utils.view_utils import render_bvp_template
from bvp.utils import time_utils
from bvp.data.services.resources import Resource
from bvp.data.models.assets import AssetType
from bvp.data.models.assets import Power


# Dashboard and main landing page
@bvp_ui.route("/")
@bvp_ui.route("/dashboard")
@login_required
def dashboard_view():
    """ Dashboard view.
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

    assets = []
    asset_counts_per_pluralised_type = {}
    current_asset_loads = {}
    for asset_type in AssetType.query.all():
        assets_by_pluralised_type = Resource(pluralize(asset_type.name)).assets
        asset_counts_per_pluralised_type[pluralize(asset_type.name)] = len(
            assets_by_pluralised_type
        )
        for asset in assets_by_pluralised_type:
            # TODO: the 2015 hack is temporary
            measured_now = Power.collect(
                [asset.name],
                query_window=(
                    time_utils.get_most_recent_quarter().replace(year=2015),
                    time_utils.get_most_recent_quarter().replace(year=2015)
                    + timedelta(minutes=15),
                ),
                resolution="15T",
            ).y
            if measured_now.size > 0:
                current_asset_loads[asset.name] = measured_now[0]
            else:
                current_asset_loads[asset.name] = 0
            assets.append(asset)

    # TODO: remove this trick to list batteries
    if current_user.has_role("admin"):
        asset_counts_per_pluralised_type[
            "batteries"
        ] = asset_counts_per_pluralised_type["solar"]

    return render_bvp_template(
        "views/dashboard.html",
        show_map=True,
        message=msg,
        assets=assets,
        asset_counts_per_pluralised_type=asset_counts_per_pluralised_type,
        current_asset_loads=current_asset_loads,
    )
