from datetime import timedelta

from flask import current_app, request
from flask_classful import FlaskView
from flask_security import login_required
from humanize import naturaldelta
from werkzeug.exceptions import NotFound
from webargs.flaskparser import use_kwargs

from flexmeasures.data import db
from flexmeasures.data.schemas import StartEndTimeSchema
from flexmeasures.data.services.timerange import get_timerange
from flexmeasures import Sensor
from flexmeasures.ui.utils.view_utils import (
    render_flexmeasures_template,
    available_units,
)
from flexmeasures.ui.utils.breadcrumb_utils import get_breadcrumb_info
from flexmeasures.ui.views.assets.utils import (
    user_can_create_children,
    user_can_delete,
    user_can_update,
)
from flexmeasures.utils.time_utils import duration_isoformat


class SensorUI(FlaskView):
    """
    This view creates several new UI endpoints for viewing sensors.

    todo: consider extending this view for crud purposes
    """

    route_base = "/sensors"
    trailing_slash = False

    @use_kwargs(StartEndTimeSchema, location="query")
    @login_required
    def get(self, id: int, **kwargs):
        """GET from /sensors/<id>
        The following query parameters are supported (should be used only together):
         - start_time: minimum time of the events to be shown
         - end_time: maximum time of the events to be shown
        """
        sensor = db.session.get(Sensor, id)
        if sensor is None:
            raise NotFound
        can_create_children = user_can_create_children(sensor)
        has_enough_data = False
        planning_horizon: timedelta = current_app.config.get(
            "FLEXMEASURES_PLANNING_HORIZON", timedelta(days=2)
        )
        forecast_default_duration_iso = duration_isoformat(planning_horizon)
        forecast_default_duration_human = naturaldelta(planning_horizon)
        forecast_default_duration_days = max(
            1, min(7, int(planning_horizon.total_seconds() / 86400))
        )
        if can_create_children:
            earliest, latest = get_timerange([sensor.id])
            has_enough_data = (latest - earliest) >= timedelta(days=2)
        return render_flexmeasures_template(
            "sensors/index.html",
            sensor=sensor,
            user_can_update_sensor=user_can_update(sensor),
            user_can_delete_sensor=user_can_delete(sensor),
            user_can_create_children_sensor=can_create_children,
            sensor_has_enough_data_for_forecast=has_enough_data,
            forecast_default_duration_iso=forecast_default_duration_iso,
            forecast_default_duration_human=forecast_default_duration_human,
            forecast_default_duration_days=forecast_default_duration_days,
            available_units=available_units(),
            msg="",
            breadcrumb_info=get_breadcrumb_info(sensor),
            event_starts_after=request.args.get("start_time"),
            event_ends_before=request.args.get("end_time"),
        )
