from flask import request, current_app
from flask_security import login_required
from flask_security.core import current_user
from sqlalchemy import select

from flexmeasures.auth.policy import user_has_admin_access
from flexmeasures.data.queries.generic_assets import get_asset_group_queries
from flexmeasures.data import db
from flexmeasures.ui.views import flexmeasures_ui
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template, clear_session
from flexmeasures.data.models.generic_assets import (
    GenericAssetType,
    get_center_location_of_assets,
)
from flexmeasures.data.services.asset_grouping import (
    AssetGroup,
)


# Dashboard (default root view, see utils/app_utils.py)
@flexmeasures_ui.route("/dashboard")
@login_required
def dashboard_view():
    """Dashboard view.
    This is the default landing page.
    It shows a map with the location of all of the assets in the user's account,
    or all assets if the user is an admin.
    Assets are grouped by asset type, which leads to map layers and a table with asset counts by type.
    Admins get to see all assets.

    TODO: Assets for which the platform has identified upcoming balancing opportunities are highlighted.
    """
    msg = ""
    if "clear-session" in request.values:
        clear_session()
        msg = "Your session was cleared."
    aggregate_type_groups = current_app.config.get("FLEXMEASURES_ASSET_TYPE_GROUPS", {})

    group_by_accounts = request.args.get("group_by_accounts", "0") != "0"
    if user_has_admin_access(current_user, "read") and group_by_accounts:
        asset_groups = get_asset_group_queries(
            group_by_type=False, group_by_account=True
        )
    else:
        asset_groups = get_asset_group_queries(
            group_by_type=True, custom_aggregate_type_groups=aggregate_type_groups
        )

    map_asset_groups = {}
    for asset_group_name, asset_group_query in asset_groups.items():
        asset_group = AssetGroup(asset_group_name, asset_query=asset_group_query)
        if any([a.location for a in asset_group.assets]):
            map_asset_groups[asset_group_name] = asset_group

    known_asset_types = [
        gat.name for gat in db.session.scalars(select(GenericAssetType)).all()
    ]

    return render_flexmeasures_template(
        "views/new_dashboard.html",
        message=msg,
        mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
        map_center=get_center_location_of_assets(user=current_user),
        known_asset_types=known_asset_types,
        asset_groups=map_asset_groups,
        aggregate_type_groups=aggregate_type_groups,
        group_by_accounts=group_by_accounts,
    )
