import json

from altair.utils.html import spec_to_html
from flask import current_app
from flask_classful import FlaskView, route
from flask_security import login_required, roles_required
from marshmallow import fields
from webargs.flaskparser import use_kwargs

from flexmeasures.data.schemas.times import AwareDateTimeField
from flexmeasures.api.dev.sensors import SensorAPI
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.ui.utils.chart_defaults import chart_options


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
            "chart_theme": fields.Str(required=False),
        },
        location="query",
    )
    def get_chart(self, id, **kwargs):
        """GET from /sensors/<id>/chart"""

        # Chart theme
        chart_theme = kwargs.pop("chart_theme", None)
        if chart_theme:
            chart_options["theme"] = chart_theme
            chart_options["tooltip"]["theme"] = chart_theme

        # Chart specs
        chart_specs = SensorAPI().get_chart(id, include_data=True, **kwargs)
        return spec_to_html(
            json.loads(chart_specs),
            mode=chart_options["mode"],
            vega_version=current_app.config.get("FLEXMEASURES_JS_VERSIONS")["vega"],
            vegaembed_version=current_app.config.get("FLEXMEASURES_JS_VERSIONS")[
                "vegaembed"
            ],
            vegalite_version=current_app.config.get("FLEXMEASURES_JS_VERSIONS")[
                "vegalite"
            ],
            embed_options=chart_options,
        )

    @login_required
    @roles_required("admin")  # todo: remove after we check for sensor ownership
    def get(self, id: int):
        """GET from /sensors/<id>"""
        return render_flexmeasures_template(
            "views/sensors.html",
            sensor_id=id,
            msg="",
        )
