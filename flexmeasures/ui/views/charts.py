from flask_security import roles_accepted
from flask_json import as_json
from bokeh.embed import json_item
from marshmallow import Schema, fields, validate
from webargs.flaskparser import use_args

from flexmeasures.api.v2_0 import flexmeasures_api as flexmeasures_api_v2_0
from flexmeasures.api.v2_0.routes import v2_0_service_listing
from flexmeasures.api.common.schemas.times import DurationField
from flexmeasures.data.queries.analytics import get_power_data
from flexmeasures.ui.views.analytics import make_power_figure


"""
An endpoint to get a power chart.

This will grow to become code for more charts eventually.
The plan is to separate charts specs from the actual data later,
and to switch to Altair.

For now, we'll keep this endpoint here, with route and implementation in the same file.
When we move forward, we'll review the architecture.
"""


v2_0_service_listing["services"].append(
    {
        "name": "GET /charts/power",
        "access": ["admin", "Prosumer"],
        "description": "Get a Bokeh chart for power data to embed in web pages.",
    },
)


class ChartRequestSchema(Schema):
    """
    This schema describes the request for a chart.
    """

    resource = fields.Str(required=True)
    start_time = fields.DateTime(required=True)
    end_time = fields.DateTime(required=True)
    resolution = DurationField(required=True)
    show_consumption_as_positive = fields.Bool(missing=True)
    show_individual_traces_for = fields.Str(
        missing="none", validate=validate.OneOf(["none", "schedules", "power"])
    )
    forecast_horizon = DurationField(missing="PT6H")


@flexmeasures_api_v2_0.route("/charts/power", methods=["GET"])
@roles_accepted("admin", "Prosumer")
@use_args(ChartRequestSchema(), location="querystring")
@as_json
def get_power_chart(chart_request):
    """API endpoint to get a chart for power data which can be embedded in web pages.

    .. :quickref: Chart; Get a power chart

    This endpoint returns a Bokeh chart with power data which can be embedded in a website.
    It includes forecasts and even schedules, if available.

    **Example request**

    An example of a chart request:

    .. sourcecode:: json

        {
            "resource": ""my-battery,
            "start_time": "2020-02-20:10:00:00UTC",
            "end_time": "2020-02-20:11:00:00UTC",
            "resolution": "PT15M",
            "consumption_as_positive": true
            "resolution": "PT6H",
            "show_individual_traces_for": "none"  // can be power or schedules
        }

    On your webpage, you need to include the Bokeh libraries, e.g.:

        <script src="https://cdn.pydata.org/bokeh/release/bokeh-1.0.4.min.js"></script>

    (The version needs to match the version used by the FlexMeasures server, see requirements/app.txt)

    Then you can call this endpoint and include the result like this:

    .. sourcecode:: javascript

        <script>
            fetch('http://localhost:5000/api/v2_0/charts/power?' + urlData.toString(),
            {
                method: "GET",
                mode: "cors",
                headers:
                    {
                        "Content-Type": "application/json",
                        "Authorization": "<users auth token>"
                    },
            })
            .then(function(response) { return response.json(); })
            .then(function(item) { Bokeh.embed.embed_item(item, "<ID of the div >"); });
        </script>

    where `urlData` is a `URLSearchData` object and contains the chart request parameters (see above).

    :reqheader Authorization: The authentication token
    :reqheader Content-Type: application/json
    :resheader Content-Type: application/json
    :status 200: PROCESSED
    :status 400: INVALID_REQUEST
    :status 401: UNAUTHORIZED
    :status 403: INVALID_SENDER
    :status 422: UNPROCESSABLE_ENTITY
    """
    data = get_power_data(
        resource=chart_request["resource"],
        show_consumption_as_positive=chart_request["show_consumption_as_positive"],
        showing_individual_traces_for=chart_request["show_individual_traces_for"],
        metrics={},  # will be stored here, we don't need them for now
        query_window=(chart_request["start_time"], chart_request["end_time"]),
        resolution=chart_request["resolution"],
        forecast_horizon=chart_request["forecast_horizon"],
    )
    figure = make_power_figure(
        resource_display_name=chart_request["resource"],
        data=data[0],
        forecast_data=data[1],
        schedule_data=data[2],
        show_consumption_as_positive=chart_request["show_consumption_as_positive"],
        shared_x_range=None,
        sizing_mode="scale_both",
    )
    return json_item(figure)
