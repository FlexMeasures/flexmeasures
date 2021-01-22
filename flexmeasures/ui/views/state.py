from flask import request
from flask_security import login_required

from flexmeasures.data.models.assets import Asset
from flexmeasures.data.services.resources import can_access_asset
from flexmeasures.ui.utils.plotting_utils import get_latest_power_as_plot
from flexmeasures.ui.views import flexmeasures_ui


@flexmeasures_ui.route("/state")
@login_required
def state_view():
    """State view.
    This returns a little html snippet with a plot of the most recent state of the asset.
    """
    asset_id = request.args.get("id")
    try:
        int(asset_id)
    except ValueError:
        return """"<script type="text/javascript">
        console.log("State not available. Asset not officially registered.");
        </script>"""
    asset = Asset.query.filter(Asset.id == asset_id).one_or_none()
    if asset is None:
        return """"<script type="text/javascript">
        console.log("State not available. No asset found.");
        </script>"""
    if not can_access_asset(asset):
        return """"<script type="text/javascript">
        console.log("State not available. No access rights for this asset.");
        </script>"""
    time_str, plot_html_str = get_latest_power_as_plot(asset, small=True)
    return plot_html_str
