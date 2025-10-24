from flask import request
from flask_classful import FlaskView
from flask_security import login_required
from werkzeug.exceptions import NotFound
from webargs.flaskparser import use_kwargs

from flexmeasures.data import db
from flexmeasures.data.schemas import StartEndTimeSchema
from flexmeasures import Sensor
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.ui.utils.breadcrumb_utils import get_breadcrumb_info
from flexmeasures.ui.views.assets.utils import (
    user_can_delete,
    user_can_update,
)


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
        return render_flexmeasures_template(
            "sensors/index.html",
            sensor=sensor,
            user_can_update_sensor=user_can_update(sensor),
            user_can_delete_sensor=user_can_delete(sensor),
            msg="",
            breadcrumb_info=get_breadcrumb_info(sensor),
            event_starts_after=request.args.get("start_time"),
            event_ends_before=request.args.get("end_time"),
        )
