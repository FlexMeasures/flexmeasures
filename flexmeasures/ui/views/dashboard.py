from collections import OrderedDict

from flask import request, current_app
from flask_security import login_required
from flask_security.core import current_user
from sqlalchemy import select

from flexmeasures.data.queries.generic_assets import get_asset_group_queries
from flexmeasures.data import db
from flexmeasures.ui.views import flexmeasures_ui
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template, clear_session
from flexmeasures.data.models.generic_assets import (
    GenericAssetType,
    get_bounding_box_of_assets,
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
    """
    msg = ""
    if "clear-session" in request.values:
        clear_session()
        msg = "Your session was cleared."
    aggregate_type_groups = current_app.config.get("FLEXMEASURES_ASSET_TYPE_GROUPS", {})

    group_by_accounts = request.args.get("group_by_accounts", "0") != "0"
    if group_by_accounts:
        asset_group_names_with_queries = get_asset_group_queries(
            group_by_type=False, group_by_account=True
        )
    else:
        asset_group_names_with_queries = get_asset_group_queries(
            group_by_type=True, custom_aggregate_type_groups=aggregate_type_groups
        )
    # Load asset groups, which queries assets; and we count assets without location
    asset_groups = []
    num_assets_without_location = 0
    for asset_group_name, asset_group_query in asset_group_names_with_queries.items():
        asset_group = AssetGroup(asset_group_name, asset_query=asset_group_query)
        asset_groups.append(asset_group)
        for asset in asset_group.assets:
            if asset.location is None:
                num_assets_without_location += 1
    # Create asset group dict for template, preserving order by count of included assets (desc)
    asset_groups.sort(key=lambda ag: ag.count, reverse=True)
    map_asset_groups = OrderedDict()
    for asset_group in asset_groups:
        map_asset_groups[asset_group.name] = asset_group
    # Get known asset types for making icons
    known_asset_types = [
        gat.name for gat in db.session.scalars(select(GenericAssetType)).all()
    ]

    bounding_box = get_bounding_box_of_assets(user=current_user)

    # If the bounding box is the server default, prompt the user to share their location
    prompt_user_for_location = False
    if bounding_box == current_app.config["FLEXMEASURES_DEFAULT_BOUNDING_BOX"]:
        prompt_user_for_location = True

    return render_flexmeasures_template(
        "dashboard.html",
        message=msg,
        mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
        bounding_box=bounding_box,
        prompt_user_for_location=prompt_user_for_location,
        known_asset_types=known_asset_types,
        asset_groups=map_asset_groups,
        num_assets_without_location=num_assets_without_location,
        aggregate_type_groups=aggregate_type_groups,
        group_by_accounts=group_by_accounts,
    )
