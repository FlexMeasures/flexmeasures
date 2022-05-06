import json
import warnings

from flask_classful import FlaskView, route
from flask_security import current_user, auth_required
from marshmallow import fields
from textwrap import wrap
from webargs.flaskparser import use_kwargs
from werkzeug.exceptions import abort

from flexmeasures.auth.policy import ADMIN_ROLE, ADMIN_READER_ROLE
from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.schemas.times import AwareDateTimeField
from flexmeasures.data.models.time_series import Sensor


class SensorAPI(FlaskView):
    """
    This view exposes sensor attributes through API endpoints under development.
    These endpoints are not yet part of our official API, but support the FlexMeasures UI.
    """

    route_base = "/sensor"
    decorators = [auth_required()]

    @route("/<id>/chart/")
    @use_kwargs(
        {"sensor": SensorIdField(data_key="id")},
        location="path",
    )
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
    def get_chart(self, id: int, sensor: Sensor, **kwargs):
        """GET from /sensor/<id>/chart

        .. :quickref: Chart; Download a chart with time series
        """
        return json.dumps(sensor.chart(**kwargs))

    @route("/<id>/chart_data/")
    @use_kwargs(
        {"sensor": SensorIdField(data_key="id")},
        location="path",
    )
    @use_kwargs(
        {
            "event_starts_after": AwareDateTimeField(format="iso", required=False),
            "event_ends_before": AwareDateTimeField(format="iso", required=False),
            "beliefs_after": AwareDateTimeField(format="iso", required=False),
            "beliefs_before": AwareDateTimeField(format="iso", required=False),
        },
        location="query",
    )
    def get_chart_data(self, id: int, sensor: Sensor, **kwargs):
        """GET from /sensor/<id>/chart_data

        .. :quickref: Chart; Download time series for use in charts

        Data for use in charts (in case you have the chart specs already).
        """
        return sensor.search_beliefs(as_json=True, **kwargs)

    @route("/<id>/chart_annotations/")
    @use_kwargs(
        {"sensor": SensorIdField(data_key="id")},
        location="path",
    )
    @use_kwargs(
        {
            "event_starts_after": AwareDateTimeField(format="iso", required=False),
            "event_ends_before": AwareDateTimeField(format="iso", required=False),
            "beliefs_after": AwareDateTimeField(format="iso", required=False),
            "beliefs_before": AwareDateTimeField(format="iso", required=False),
        },
        location="query",
    )
    def get_chart_annotations(self, id: int, sensor: Sensor, **kwargs):
        """GET from /sensor/<id>/chart_annotations

        .. :quickref: Chart; Download annotations for use in charts

        Annotations for use in charts (in case you have the chart specs already).
        """
        df = sensor.generic_asset.search_annotations(
            annotation_starts_after=kwargs.get("event_starts_after", None),
            annotation_ends_before=kwargs.get("event_ends_before", None),
            as_frame=True,
        )

        # Wrap on whitespace with some max line length
        df['content'] = df['content'].apply(wrap, args=[60])

        # Return JSON records
        df = df.reset_index()
        df["source"] = df["source"].astype(str)
        return df.to_json(orient="records")

    @route("/<id>/")
    @use_kwargs(
        {"sensor": SensorIdField(data_key="id")},
        location="path",
    )
    def get(self, id: int, sensor: Sensor):
        """GET from /sensor/<id>

        .. :quickref: Chart; Download sensor attributes for use in charts
        """
        attributes = ["name", "timezone", "timerange"]
        return {attr: getattr(sensor, attr) for attr in attributes}


def get_sensor_or_abort(id: int) -> Sensor:
    """
    Util function to help the GET requests. Will be obsolete..
    """
    warnings.warn(
        "Util function will be deprecated. Switch to using SensorIdField to suppress this warning.",
        FutureWarning,
    )
    sensor = Sensor.query.filter(Sensor.id == id).one_or_none()
    if sensor is None:
        raise abort(404, f"Sensor {id} not found")
    if not (
        current_user.has_role(ADMIN_ROLE)
        or current_user.has_role(ADMIN_READER_ROLE)
        or sensor.generic_asset.owner is None  # public
        or sensor.generic_asset.owner == current_user.account  # private but authorized
    ):
        raise abort(403)
    return sensor
