from flask import request
from flask_security import auth_required
from webargs.flaskparser import use_kwargs

from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data.models.assets import Asset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.resources import can_access_asset
from flexmeasures.api.common.schemas.sensors import SensorIdField
from flexmeasures.ui.utils.plotting_utils import (
    get_latest_power_as_plot as legacy_get_latest_power_as_plot,
)
from flexmeasures.ui.charts.latest_state import get_latest_power_as_plot
from flexmeasures.ui.views import flexmeasures_ui


@flexmeasures_ui.route("/sensor/<id>/state")
@use_kwargs({"sensor": SensorIdField(data_key="id")}, location="path")
@permission_required_for_context("read", arg_name="sensor")
def sensor_state_view(id: int, sensor: Sensor):
    """Sensor state view.
    This returns a little html snippet with a plot of the most recent state of the sensor.
    """
    if not sensor.has_attribute("capacity_in_mw"):
        return """"<script type="text/javascript">
        console.log("State not available. Sensor is not a power sensor.");
        </script>"""
    time_str, plot_html_str = get_latest_power_as_plot(sensor, small=True)
    return plot_html_str


@flexmeasures_ui.route("/state")
@auth_required()
def state_view():
    """State view.
    This returns a little html snippet with a plot of the most recent state of the asset.

    TODO: This is legacy ― it uses the old database model.
    """
    asset_id = request.args.get("id")
    try:
        int(asset_id)
    except ValueError:
        return """"<script type="text/javascript">
        console.log("State not available. Asset not officially registered.");
        </script>"""
    # TODO: try Sensor, then Asset (legacy)?
    asset = Asset.query.filter(Asset.id == asset_id).one_or_none()
    if asset is None:
        return """"<script type="text/javascript">
        console.log("State not available. No asset found.");
        </script>"""
    if not can_access_asset(asset):
        return """"<script type="text/javascript">
        console.log("State not available. No access rights for this asset.");
        </script>"""
    time_str, plot_html_str = legacy_get_latest_power_as_plot(asset, small=True)
    return plot_html_str
