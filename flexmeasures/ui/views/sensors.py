from altair.utils.html import spec_to_html
from flask import current_app
from flask_classful import FlaskView, route
from flask_security import login_required, roles_required
from marshmallow import fields
from webargs.flaskparser import use_kwargs

from flexmeasures.data.schemas.times import AwareDateTimeField
from flexmeasures.api.dev.sensors import SensorAPI
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
        chart_specs = SensorAPI().get_chart(
            id, include_data=True, as_html=True, **kwargs
        )
        return spec_to_html(
            chart_specs,
            "vega-lite",
            vega_version=current_app.config.get("FLEXMEASURES_JS_VERSIONS").vega,
            vegaembed_version=current_app.config.get(
                "FLEXMEASURES_JS_VERSIONS"
            ).vegaembed,
            vegalite_version=current_app.config.get(
                "FLEXMEASURES_JS_VERSIONS"
            ).vegalite,
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
