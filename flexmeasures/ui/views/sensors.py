from flask_classful import FlaskView, route
from flask_security import login_required, roles_required
from marshmallow import fields
from webargs.flaskparser import use_kwargs

from flexmeasures.api.common.schemas.times import AwareDateTimeField
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template


class SensorView(FlaskView):
    """
    This view exposes sensor attributes through the API.

    todo: consider extending this view for crud purposes
    """

    route_base = "/sensors"

    @login_required
    @roles_required("admin")  # todo: remove after we check for sensor ownership
    @route("/<id>/<attr>/")
    @use_kwargs(
        {
            "events_not_before": AwareDateTimeField(format="iso", required=False),
            "events_before": AwareDateTimeField(format="iso", required=False),
            "beliefs_not_before": AwareDateTimeField(format="iso", required=False),
            "beliefs_before": AwareDateTimeField(format="iso", required=False),
            "data_only": fields.Boolean(required=False),
            "chart_only": fields.Boolean(required=False),
            "as_html": fields.Boolean(required=False),
        },
        location="query",
    )
    def get_attr(self, id, attr, **kwargs):
        """GET from /sensors/<id>/<attr>"""
        sensor = Sensor.query.filter(Sensor.id == id).one_or_none()
        sensor_attr = getattr(sensor, attr)
        if not callable(sensor_attr):
            # property
            return {attr: sensor_attr}
        else:
            # method
            return sensor_attr(**kwargs)

    @login_required
    @roles_required("admin")  # todo: remove after we check for sensor ownership
    def get(self, id: str):
        """GET from /sensors/<id>"""
        return render_flexmeasures_template(
            ("views/sensors.html"),
            sensor_id=id,
            msg="",
        )
