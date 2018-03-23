from datetime import timedelta

from flask import request, session
from inflection import pluralize

from views import bvp_views
from views.utils import render_bvp_template, check_prosumer_mock, filter_mock_prosumer_assets
from utils import time_utils
from utils.data_access import get_data_for_assets, Resource
import models


# Dashboard and main landing page
@bvp_views.route('/')
@bvp_views.route('/dashboard')
def dashboard_view():
    """ Dashboard view.
    This is the default landing page for the platform user.
    It shows a map with the location and status of all of the user's assets,
    as well as a breakdown of the asset types in the user's portfolio.
    Assets for which the platform has identified upcoming balancing opportunities are highlighted.
    """
    msg = ""
    if "clear-session" in request.values:
        session.clear()
        msg = "Your session was cleared."

    assets = []
    asset_counts_per_pluralised_type = {}
    current_asset_loads = {}
    is_prosumer_mock = check_prosumer_mock()
    for asset_type in models.asset_types:
        assets_by_pluralised_type = Resource(pluralize(asset_type)).assets
        if is_prosumer_mock:
            assets_by_pluralised_type = filter_mock_prosumer_assets(assets_by_pluralised_type)
        asset_counts_per_pluralised_type[pluralize(asset_type)] = len(assets_by_pluralised_type)
        for asset in assets_by_pluralised_type:
            # TODO: this is temporary
            current_asset_loads[asset.name] =\
                get_data_for_assets([asset.name],
                                    time_utils.get_most_recent_quarter().replace(year=2015),
                                    time_utils.get_most_recent_quarter().replace(year=2015) + timedelta(minutes=15),
                                    "15T").y[0]
            assets.append(asset)

    # Todo: switch from this mock-up function for asset counts to a proper implementation of battery assets
    if not is_prosumer_mock:
        asset_counts_per_pluralised_type["batteries"] = asset_counts_per_pluralised_type["solar"]

    return render_bvp_template('dashboard.html', show_map=True, message=msg,
                               assets=assets,
                               asset_counts_per_pluralised_type=asset_counts_per_pluralised_type,
                               current_asset_loads=current_asset_loads,
                               prosumer_mock=session.get("prosumer_mock", "0"))
