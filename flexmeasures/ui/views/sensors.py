from flask import abort
from flask_classful import FlaskView, route
from flask_security import login_required, roles_required
from marshmallow import fields
from webargs.flaskparser import use_kwargs

from flexmeasures.api.common.schemas.times import AwareDateTimeField
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template


class SensorUI(FlaskView):
    """
    This view creates several new UI endpoints for viewing sensors.

    todo: consider extending this view for crud purposes
    """

    route_base = "/sensors"

    @login_required
    @roles_required("admin")  # todo: remove after we check for sensor ownership
    @route("/<id>/chart/")
    @use_kwargs(
        {
            "event_starts_after": AwareDateTimeField(format="iso", required=False),
            "event_ends_before": AwareDateTimeField(format="iso", required=False),
            "beliefs_after": AwareDateTimeField(format="iso", required=False),
            "beliefs_before": AwareDateTimeField(format="iso", required=False),
            "dataset_name": fields.Str(required=False),
        },
        location="query",
    )
    def get_chart(self, id, **kwargs):
        """GET from /sensors/<id>/chart"""
        return SensorAPI().get_chart(id, include_data=True, as_html=True, **kwargs)

    @login_required
    @roles_required("admin")  # todo: remove after we check for sensor ownership
    def get(self, id: int):
        """GET from /sensors/<id>"""
        return render_flexmeasures_template(
            "views/sensors.html",
            sensor_id=id,
            msg="",
        )


class SensorAPI(FlaskView):
    """
    This view exposes sensor attributes through API endpoints under development.
    These endpoints are not yet part of our official API, but support the FlexMeasures UI.
    """

    route_base = "/sensor"

    @login_required
    @roles_required("admin")  # todo: remove after we check for sensor ownership
    @route("/<id>/chart/")
    @use_kwargs(
        {
            "event_starts_after": AwareDateTimeField(format="iso", required=False),
            "event_ends_before": AwareDateTimeField(format="iso", required=False),
            "beliefs_after": AwareDateTimeField(format="iso", required=False),
            "beliefs_before": AwareDateTimeField(format="iso", required=False),
            "include_data": fields.Boolean(required=False),
            "as_html": fields.Boolean(required=False),
            "dataset_name": fields.Str(required=False),
        },
        location="query",
    )
    def get_chart(self, id, **kwargs):
        """GET from /sensor/<id>/chart"""
        sensor = get_sensor_or_abort(id)
        return sensor.chart(**kwargs)

    @login_required
    @roles_required("admin")  # todo: remove after we check for sensor ownership
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
        return sensor.chart_data(**kwargs)

    @login_required
    @roles_required("admin")  # todo: remove after we check for sensor ownership
    def get(self, id: int):
        """GET from /sensor/<id>"""
        sensor = get_sensor_or_abort(id)
        attributes = ["name", "timezone", "timerange"]
        return {attr: getattr(sensor, attr) for attr in attributes}


def get_sensor_or_abort(id: int) -> Sensor:
    sensor = Sensor.query.filter(Sensor.id == id).one_or_none()
    if sensor is None:
        raise abort(404, f"Sensor {id} not found")
    return sensor
