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
    DurationField,
    SensorIdField,
)
from flexmeasures.api.common.schemas.generic_schemas import (
    EventWindowSchema,
    BeliefTimeFilterSchema,
)
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.annotations import prepare_annotations_for_chart
from flexmeasures.ui.utils.view_utils import set_session_variables


class SensorChartKwargsSchema(EventWindowSchema, BeliefTimeFilterSchema):
    legacy_field_aliases = {
        **EventWindowSchema.legacy_field_aliases,
        **BeliefTimeFilterSchema.legacy_field_aliases,
        "include_data": "include-data",
        "include_sensor_annotations": "include-sensor-annotations",
        "include_asset_annotations": "include-asset-annotations",
        "include_account_annotations": "include-account-annotations",
        "dataset_name": "dataset-name",
        "chart_type": "chart-type",
    }

    include_data = fields.Boolean(
        data_key="include-data",
        required=False,
        metadata=dict(
            description="If true, chart specs include the data; if false, fetch data separately from the `chart_data` endpoint.",
        ),
    )
    include_sensor_annotations = fields.Boolean(
        data_key="include-sensor-annotations",
        required=False,
        metadata=dict(
            description="If true, include the sensor's own annotations in the chart.",
        ),
    )
    include_asset_annotations = fields.Boolean(
        data_key="include-asset-annotations",
        required=False,
        metadata=dict(
            description="If true, include the sensor's asset's annotations in the chart.",
        ),
    )
    include_account_annotations = fields.Boolean(
        data_key="include-account-annotations",
        required=False,
        metadata=dict(
            description="If true, include the sensor's account's annotations in the chart.",
        ),
    )
    dataset_name = fields.Str(
        data_key="dataset-name",
        required=False,
        metadata=dict(
            description="Name to use for the embedded chart dataset.",
        ),
    )
    chart_type = fields.Str(
        data_key="chart-type",
        required=False,
        metadata=dict(
            description="Chart type, e.g. 'bar_chart' or 'daily_heatmap'.",
        ),
    )
    height = fields.Str(
        required=False,
        metadata=dict(
            description="Chart height in pixels; without it, FlexMeasures sets a default.",
        ),
    )
    width = fields.Str(
        required=False,
        metadata=dict(
            description="Chart width in pixels; without it, the chart is scaled to the full width of its container.",
        ),
    )


class SensorChartDataKwargsSchema(EventWindowSchema, BeliefTimeFilterSchema):
    legacy_field_aliases = {
        **EventWindowSchema.legacy_field_aliases,
        **BeliefTimeFilterSchema.legacy_field_aliases,
        "use_latest_version_per_event": "use-latest-version-per-event",
        "most_recent_beliefs_only": "most-recent-beliefs-only",
        "compress_json": "compress-json",
    }

    resolution = DurationField(
        required=False,
        metadata=dict(
            description="Resolution of the requested data, in ISO 8601 duration format.",
            example="PT15M",
        ),
    )
    use_latest_version_per_event = fields.Boolean(
        data_key="use-latest-version-per-event",
        required=False,
        load_default=True,
        metadata=dict(
            description="If true (default), only the latest version of each event's belief is returned.",
        ),
    )
    most_recent_beliefs_only = fields.Boolean(
        data_key="most-recent-beliefs-only",
        required=False,
        load_default=True,
        metadata=dict(
            description="If true (default), return only the most recently recorded belief for each event; if false, return every recorded belief.",
        ),
    )
    compress_json = fields.Boolean(
        data_key="compress-json",
        required=False,
        metadata=dict(
            description="If true, compress the JSON response.",
        ),
    )


class SensorChartAnnotationsKwargsSchema(EventWindowSchema, BeliefTimeFilterSchema):
    legacy_field_aliases = {
        **EventWindowSchema.legacy_field_aliases,
        **BeliefTimeFilterSchema.legacy_field_aliases,
    }

    clip = fields.Boolean(
        load_default=True,
        metadata=dict(
            description="If true (default), clip annotations to the requested time window.",
        ),
    )


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
    @use_kwargs(SensorChartKwargsSchema, location="query")
    @permission_required_for_context("read", ctx_arg_name="sensor")
    def get_chart(self, id: int, sensor: Sensor, **kwargs):
        """GET from /sensor/<id>/chart

        .. :quickref: Chart; Download a chart with time series

        **Optional fields**

        - "start" (legacy alias: "event_starts_after"; see the `timely-beliefs documentation <https://github.com/SeitaBV/timely-beliefs/blob/main/timely_beliefs/docs/timing.md/#events-and-sensors>`_). May be given alone, or paired with "duration" to derive "end".
        - "end" (legacy alias: "event_ends_before"; see the `timely-beliefs documentation <https://github.com/SeitaBV/timely-beliefs/blob/main/timely_beliefs/docs/timing.md/#events-and-sensors>`_). May be given alone, or paired with "duration" to derive "start".
        - "duration" (ISO 8601 duration format; provide together with "start" or "end" to derive the other bound)
        - "prior" (legacy alias: "beliefs_before"; see the `timely-beliefs documentation <https://github.com/SeitaBV/timely-beliefs/blob/main/timely_beliefs/docs/timing.md/#events-and-sensors>`_)
        - "include-data" (legacy alias: "include_data"; if true, chart specs include the data; if false, use the `GET /api/dev/sensor/(id)/chart_data <../api/dev.html#get--api-dev-sensor-(id)-chart_data->`_ endpoint to fetch data)
        - "chart-type" (legacy alias: "chart_type"; currently 'bar_chart' and 'daily_heatmap' are supported types)
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
    @use_kwargs(SensorChartDataKwargsSchema, location="query")
    @permission_required_for_context("read", ctx_arg_name="sensor")
    def get_chart_data(self, id: int, sensor: Sensor, **kwargs):
        """GET from /sensor/<id>/chart_data

        .. :quickref: Chart; Download time series for use in charts

        Data for use in charts (in case you have the chart specs already).

        **Optional fields**

        - "start" (legacy alias: "event_starts_after"; see the `timely-beliefs documentation <https://github.com/SeitaBV/timely-beliefs/blob/main/timely_beliefs/docs/timing.md/#events-and-sensors>`_). May be given alone, or paired with "duration" to derive "end".
        - "end" (legacy alias: "event_ends_before"; see the `timely-beliefs documentation <https://github.com/SeitaBV/timely-beliefs/blob/main/timely_beliefs/docs/timing.md/#events-and-sensors>`_). May be given alone, or paired with "duration" to derive "start".
        - "duration" (ISO 8601 duration format; provide together with "start" or "end" to derive the other bound)
        - "prior" (legacy alias: "beliefs_before"; see the `timely-beliefs documentation <https://github.com/SeitaBV/timely-beliefs/blob/main/timely_beliefs/docs/timing.md/#events-and-sensors>`_)
        - "resolution" (see [docs about describing timing](https://flexmeasures.readthedocs.io/latest/api/notation.html#frequency-and-resolution))
        - "most-recent-beliefs-only" (legacy alias: "most_recent_beliefs_only"; if true, returns the most recent belief for each event; if false, returns each belief for each event; defaults to true)
        """
        return sensor.search_beliefs(as_json=True, **kwargs)

    @route("/<id>/chart_annotations", strict_slashes=False)
    @use_kwargs(
        {"sensor": SensorIdField(data_key="id")},
        location="path",
    )
    @use_kwargs(SensorChartAnnotationsKwargsSchema, location="query")
    @permission_required_for_context("read", ctx_arg_name="sensor")
    def get_chart_annotations(self, id: int, sensor: Sensor, **kwargs):
        """GET from /sensor/<id>/chart_annotations

        .. :quickref: Chart; Download annotations for use in charts

        Annotations for use in charts (in case you have the chart specs already).
        """
        event_starts_after = kwargs.get("event_starts_after", None)
        event_ends_before = kwargs.get("event_ends_before", None)
        df = sensor.search_annotations(
            annotations_after=event_starts_after,
            annotations_before=event_ends_before,
            beliefs_after=kwargs.get("beliefs_after", None),
            beliefs_before=kwargs.get("beliefs_before", None),
            include_asset_annotations=True,
            as_frame=True,
        )
        if kwargs["clip"]:
            df["start"] = df["start"].clip(lower=event_starts_after)
            df["end"] = df["end"].clip(upper=event_ends_before)

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
