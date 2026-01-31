from flask_classful import FlaskView, route
from sqlalchemy import select
from flask_security import auth_required
from flask_json import as_json

from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.schemas.sources import DataSourceSchema


source_schema = DataSourceSchema()


class DataSourcesAPI(FlaskView):
    """
    This API view exposes data sources.
    """

    route_base = "/sources"
    trailing_slash = False
    decorators = [auth_required()]

    @route("", methods=["GET"])
    @as_json
    def index(self):
        """
        .. :quickref: Sources; Get list of available data sources
        ---
        get:
          summary: Get list of available data sources
          description: |
            Get list of data sources which are currently known.
            Any data ingested into FlexMeasures is associated with a data source.
            This is important for traceability and accountability.
            Also, data can be treated differently based on its source type, e.g. when looking up schedules.
          security:
            - ApiKeyAuth: []
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  schema: DataSourcesSchema
                  examples:
                    single_data_source:
                      summary: One data source being returned in the response
                      value:
                        - id: 1
                          name: solar
                          type: forecaster
          tags:
            - Sources
        """
        response = source_schema.dump(
            db.session.scalars(select(DataSource)).all(), many=True
        )
        return response, 200
