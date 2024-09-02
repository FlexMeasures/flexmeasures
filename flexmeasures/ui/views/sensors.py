import json

from altair.utils.html import spec_to_html
from flask import current_app, request
from flask_classful import FlaskView, route
from flask_security import auth_required, login_required
from marshmallow import fields
from webargs.flaskparser import use_kwargs

from flexmeasures.data import db
from flexmeasures.data.schemas import StartEndTimeSchema
from flexmeasures.data.schemas.times import AwareDateTimeField
from flexmeasures.api.dev.sensors import SensorAPI
from flexmeasures import Sensor
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.ui.utils.chart_defaults import chart_options
from flexmeasures.ui.utils.breadcrumb_utils import get_breadcrumb_info


class SensorUI(FlaskView):
    """
    This view creates several new UI endpoints for viewing sensors.

    todo: consider extending this view for crud purposes
    """

    route_base = "/sensors"
    trailing_slash = False

    @auth_required()
    @route("/<id>/chart")
    @use_kwargs(
        {
            "event_starts_after": AwareDateTimeField(format="iso", required=False),
            "event_ends_before": AwareDateTimeField(format="iso", required=False),
            "beliefs_after": AwareDateTimeField(format="iso", required=False),
            "beliefs_before": AwareDateTimeField(format="iso", required=False),
            "include_sensor_annotations": fields.Bool(required=False),
            "include_asset_annotations": fields.Bool(required=False),
            "include_account_annotations": fields.Bool(required=False),
            "dataset_name": fields.Str(required=False),
            "chart_theme": fields.Str(required=False),
        },
        location="query",
    )
    def get_chart(self, id, **kwargs):
        """GET from /sensors/<id>/chart"""

        # Chart theme
        chart_theme = kwargs.pop("chart_theme", None)
        embed_options = chart_options.copy()
        if chart_theme:
            embed_options["theme"] = chart_theme
            embed_options["tooltip"]["theme"] = chart_theme

        # Chart specs
        chart_specs = SensorAPI().get_chart(id, include_data=True, **kwargs)
        return spec_to_html(
            json.loads(chart_specs),
            mode=embed_options["mode"],
            vega_version=current_app.config.get("FLEXMEASURES_JS_VERSIONS")["vega"],
            vegaembed_version=current_app.config.get("FLEXMEASURES_JS_VERSIONS")[
                "vegaembed"
            ],
            vegalite_version=current_app.config.get("FLEXMEASURES_JS_VERSIONS")[
                "vegalite"
            ],
            embed_options=embed_options,
        ).replace('<div id="vis"></div>', '<div id="vis" style="width: 100%;"></div>')

    @use_kwargs(StartEndTimeSchema, location="query")
    @login_required
    def get(self, id: int, **kwargs):
        """GET from /sensors/<id>
        The following query parameters are supported (should be used only together):
         - start_time: minimum time of the events to be shown
         - end_time: maximum time of the events to be shown
        """
        sensor = db.session.get(Sensor, id)
        return render_flexmeasures_template(
            "views/sensors.html",
            sensor=sensor,
            msg="",
            breadcrumb_info=get_breadcrumb_info(sensor),
            event_starts_after=request.args.get("start_time"),
            event_ends_before=request.args.get("end_time"),
        )
