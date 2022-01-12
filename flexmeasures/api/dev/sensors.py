import json

from flask_classful import FlaskView, route
from flask_security import current_user, auth_required
from marshmallow import fields
from webargs.flaskparser import use_kwargs
from werkzeug.exceptions import abort

from flexmeasures.auth.policy import ADMIN_ROLE
from flexmeasures.data.schemas.times import AwareDateTimeField
from flexmeasures.data.models.time_series import Sensor


class SensorAPI(FlaskView):
    """
    This view exposes sensor attributes through API endpoints under development.
    These endpoints are not yet part of our official API, but support the FlexMeasures UI.
    """

    route_base = "/sensor"

    @auth_required()
    @route("/<id>/chart/")
    @use_kwargs(
        {
            "event_starts_after": AwareDateTimeField(format="iso", required=False),
            "event_ends_before": AwareDateTimeField(format="iso", required=False),
            "beliefs_after": AwareDateTimeField(format="iso", required=False),
            "beliefs_before": AwareDateTimeField(format="iso", required=False),
            "include_data": fields.Boolean(required=False),
            "dataset_name": fields.Str(required=False),
            "height": fields.Str(required=False),
            "width": fields.Str(required=False),
        },
        location="query",
    )
    def get_chart(self, id, **kwargs):
        """GET from /sensor/<id>/chart"""
        sensor = get_sensor_or_abort(id)
        return json.dumps(sensor.chart(**kwargs))

    @auth_required()
    @route("/<id>/chart_data/")
    @use_kwargs(
        {
            "event_starts_after": AwareDateTimeField(format="iso", required=False),
            "event_ends_before": AwareDateTimeField(format="iso", required=False),
            "beliefs_after": AwareDateTimeField(format="iso", required=False),
            "beliefs_before": AwareDateTimeField(format="iso", required=False),
        },
        location="query",
    )
    def get_chart_data(self, id, **kwargs):
        """GET from /sensor/<id>/chart_data

        Data for use in charts (in case you have the chart specs already).
        """
        sensor = get_sensor_or_abort(id)
        return sensor.search_beliefs(as_json=True, **kwargs)

    @auth_required()
    def get(self, id: int):
        """GET from /sensor/<id>"""
        sensor = get_sensor_or_abort(id)
        attributes = ["name", "timezone", "timerange"]
        return {attr: getattr(sensor, attr) for attr in attributes}


def get_sensor_or_abort(id: int) -> Sensor:
    sensor = Sensor.query.filter(Sensor.id == id).one_or_none()
    if sensor is None:
        raise abort(404, f"Sensor {id} not found")
    if not (
        current_user.has_role(ADMIN_ROLE)
        or sensor.generic_asset.owner is None  # public
        or sensor.generic_asset.owner == current_user.account  # private but authorized
    ):
        raise abort(403)
    return sensor
