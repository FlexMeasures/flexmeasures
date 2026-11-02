from __future__ import annotations

from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required

from flexmeasures.api.common.responses import ResponseTuple
from flexmeasures.data.services.report_templates import (
    describe_placeholders,
    get_report_template,
    list_report_templates,
)

"""
API endpoints to list the prepared report templates, which a reporting automation can start from.
"""


def _with_placeholders(template: dict) -> dict:
    """A template as the API returns it: as packaged, plus a description of each placeholder it leaves open."""
    return dict(template, placeholders=describe_placeholders(template))


class ReportTemplateAPI(FlaskView):
    route_base = "/report-templates"
    trailing_slash = False
    decorators = [auth_required()]

    @route("", methods=["GET"])
    @as_json
    def index(self):
        """List the prepared report templates.

        .. :quickref: Reports; List the prepared report templates.

        ---
        get:
          summary: List the prepared report templates.
          description: |
            Returns the report templates packaged with FlexMeasures, sorted by name.
            Each template is a ready-made report definition: a reporter, its config and a parameters skeleton.
            The values to fill in, mostly sensor IDs, are left as ``FILL_IN`` placeholders,
            and the ``placeholders`` list describes each of them, so that a form can offer one field per placeholder:

            - ``section``: whether the placeholder is in the ``config`` or in the ``parameters``.
            - ``path`` and ``location``: where it sits in that section, as a path and as the keys and indexes leading to it.
            - ``kind``: ``sensor`` for a placeholder taking a sensor ID, ``value`` for any other.
            - ``label``: a short label for the field.

            Fill in every placeholder before creating a reporting automation from a template;
            an automation with a placeholder left in is refused.
            The templates are the same for every user, so any logged-in user may list them.
          security:
            - ApiKeyAuth: []
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  example:
                    report-templates:
                      - name: daily-energy
                        description: Daily energy total from a single power or energy sensor.
                        reporter: PandasReporter
                        config:
                          required_input:
                            - name: energy
                              unit: kWh
                          required_output:
                            - name: daily-energy
                              unit: kWh
                          transformations:
                            - df_input: energy
                              df_output: daily-energy
                              method: resample_events
                              args: ["1D"]
                              kwargs:
                                method: sum
                        parameters:
                          input:
                            - name: energy
                              sensor: FILL_IN
                          output:
                            - name: daily-energy
                              sensor: FILL_IN
                          start-offset: -1D,DB
                          end-offset: DB
                        placeholders:
                          - section: parameters
                            path: input[0].sensor
                            location: [input, 0, sensor]
                            kind: sensor
                            label: "Input sensor: energy"
                          - section: parameters
                            path: output[0].sensor
                            location: [output, 0, sensor]
                            kind: sensor
                            label: "Output sensor: daily-energy"
            401:
              description: UNAUTHORIZED
          tags:
            - Reports
        """
        return {
            "report-templates": [
                _with_placeholders(template) for template in list_report_templates()
            ]
        }, 200

    @route("/<name>", methods=["GET"])
    @as_json
    def get(self, name: str) -> ResponseTuple:
        """Get one prepared report template.

        .. :quickref: Reports; Get one prepared report template.

        ---
        get:
          summary: Get one prepared report template.
          description: |
            Returns one of the report templates packaged with FlexMeasures,
            in the same shape as each template in the listing, including the description of its placeholders.
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: name
              required: true
              description: Name of the report template, such as ``self-consumption``.
              schema:
                type: string
          responses:
            200:
              description: PROCESSED
            401:
              description: UNAUTHORIZED
            404:
              description: RESOURCE_NOT_FOUND
          tags:
            - Reports
        """
        template = get_report_template(name)
        if template is None:
            return {"message": f"No report template is named '{name}'."}, 404
        return _with_placeholders(template), 200
