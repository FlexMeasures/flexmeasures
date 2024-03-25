import json
import warnings

from flask_classful import FlaskView, route
from flask_security import current_user
from marshmallow import fields
from webargs.flaskparser import use_kwargs
from werkzeug.exceptions import abort

from flexmeasures.data import db
from flexmeasures.auth.policy import ADMIN_ROLE, ADMIN_READER_ROLE
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data.schemas import (
    AssetIdField,
    AwareDateTimeField,
    DurationField,
    SensorIdField,
)
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.annotations import prepare_annotations_for_chart
from flexmeasures.ui.utils.view_utils import set_session_variables


class SensorAPI(FlaskView):
    """
    This view exposes sensor attributes through API endpoints under development.
    These endpoints are not yet part of our official API, but support the FlexMeasures UI.
    """

    route_base = "/sensor"
    trailing_slash = False
    # Note: when promoting these endpoints to the main API, we aim to be strict with trailing slashes, see #1014

    @route("/<id>/chart", strict_slashes=False)
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
            "include_sensor_annotations": fields.Boolean(required=False),
            "include_asset_annotations": fields.Boolean(required=False),
            "include_account_annotations": fields.Boolean(required=False),
            "dataset_name": fields.Str(required=False),
            "chart_type": fields.Str(required=False),
            "height": fields.Str(required=False),
            "width": fields.Str(required=False),
        },
        location="query",
    )
    @permission_required_for_context("read", ctx_arg_name="sensor")
    def get_chart(self, id: int, sensor: Sensor, **kwargs):
        """GET from /sensor/<id>/chart

        .. :quickref: Chart; Download a chart with time series

        **Optional fields**

        - "event_starts_after" (see the `timely-beliefs documentation <https://github.com/SeitaBV/timely-beliefs/blob/main/timely_beliefs/docs/timing.md/#events-and-sensors>`_)
        - "event_ends_before" (see the `timely-beliefs documentation <https://github.com/SeitaBV/timely-beliefs/blob/main/timely_beliefs/docs/timing.md/#events-and-sensors>`_)
        - "beliefs_after" (see the `timely-beliefs documentation <https://github.com/SeitaBV/timely-beliefs/blob/main/timely_beliefs/docs/timing.md/#events-and-sensors>`_)
        - "beliefs_before" (see the `timely-beliefs documentation <https://github.com/SeitaBV/timely-beliefs/blob/main/timely_beliefs/docs/timing.md/#events-and-sensors>`_)
        - "include_data" (if true, chart specs include the data; if false, use the `GET /api/dev/sensor/(id)/chart_data <../api/dev.html#get--api-dev-sensor-(id)-chart_data->`_ endpoint to fetch data)
        - "chart_type" (currently 'bar_chart' and 'daily_heatmap' are supported types)
        - "width" (an integer number of pixels; without it, the chart will be scaled to the full width of the container (hint: use ``<div style="width: 100%;">`` to set a div width to 100%)
        - "height" (an integer number of pixels; without it, FlexMeasures sets a default, currently 300)
        """
        # Store selected time range and chart type as session variables, for a consistent UX across UI page loads
        set_session_variables("event_starts_after", "event_ends_before", "chart_type")
        return json.dumps(sensor.chart(**kwargs))

    @route("/<id>/chart_data", strict_slashes=False)
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
            "resolution": DurationField(required=False),
            "most_recent_beliefs_only": fields.Boolean(required=False, default=True),
        },
        location="query",
    )
    @permission_required_for_context("read", ctx_arg_name="sensor")
    def get_chart_data(self, id: int, sensor: Sensor, **kwargs):
        """GET from /sensor/<id>/chart_data

        .. :quickref: Chart; Download time series for use in charts

        Data for use in charts (in case you have the chart specs already).

        **Optional fields**

        - "event_starts_after" (see the `timely-beliefs documentation <https://github.com/SeitaBV/timely-beliefs/blob/main/timely_beliefs/docs/timing.md/#events-and-sensors>`_)
        - "event_ends_before" (see the `timely-beliefs documentation <https://github.com/SeitaBV/timely-beliefs/blob/main/timely_beliefs/docs/timing.md/#events-and-sensors>`_)
        - "beliefs_after" (see the `timely-beliefs documentation <https://github.com/SeitaBV/timely-beliefs/blob/main/timely_beliefs/docs/timing.md/#events-and-sensors>`_)
        - "beliefs_before" (see the `timely-beliefs documentation <https://github.com/SeitaBV/timely-beliefs/blob/main/timely_beliefs/docs/timing.md/#events-and-sensors>`_)
        - "resolution" (see :ref:`resolutions`)
        - "most_recent_beliefs_only" (if true, returns the most recent belief for each event; if false, returns each belief for each event; defaults to true)
        """
        return sensor.search_beliefs(as_json=True, **kwargs)

    @route("/<id>/chart_annotations", strict_slashes=False)
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
    @permission_required_for_context("read", ctx_arg_name="sensor")
    def get_chart_annotations(self, id: int, sensor: Sensor, **kwargs):
        """GET from /sensor/<id>/chart_annotations

        .. :quickref: Chart; Download annotations for use in charts

        Annotations for use in charts (in case you have the chart specs already).
        """
        event_starts_after = kwargs.get("event_starts_after", None)
        event_ends_before = kwargs.get("event_ends_before", None)
        df = sensor.generic_asset.search_annotations(
            annotations_after=event_starts_after,
            annotations_before=event_ends_before,
            as_frame=True,
        )

        # Wrap and stack annotations
        df = prepare_annotations_for_chart(df)

        # Return JSON records
        df = df.reset_index()
        df["source"] = df["source"].astype(str)
        return df.to_json(orient="records")

    @route("/<id>", strict_slashes=False)
    @use_kwargs(
        {"sensor": SensorIdField(data_key="id")},
        location="path",
    )
    @permission_required_for_context("read", ctx_arg_name="sensor")
    def get(self, id: int, sensor: Sensor):
        """GET from /sensor/<id>

        .. :quickref: Chart; Download sensor attributes for use in charts
        """
        attributes = ["name", "timezone", "timerange"]
        return {attr: getattr(sensor, attr) for attr in attributes}


class AssetAPI(FlaskView):
    """
    This view exposes asset attributes through API endpoints under development.
    These endpoints are not yet part of our official API, but support the FlexMeasures UI.
    """

    route_base = "/asset"
    trailing_slash = False

    @route("/<id>", strict_slashes=False)
    @use_kwargs(
        {"asset": AssetIdField(data_key="id")},
        location="path",
    )
    @permission_required_for_context("read", ctx_arg_name="asset")
    def get(self, id: int, asset: GenericAsset):
        """GET from /asset/<id>

        .. :quickref: Chart; Download asset attributes for use in charts
        """
        attributes = ["name", "timezone", "timerange_of_sensors_to_show"]
        return {attr: getattr(asset, attr) for attr in attributes}


def get_sensor_or_abort(id: int) -> Sensor:
    """
    Util function to help the GET requests. Will be obsolete..
    """
    warnings.warn(
        "Util function will be deprecated. Switch to using SensorIdField to suppress this warning.",
        FutureWarning,
    )
    sensor = db.session.get(Sensor, id)
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
