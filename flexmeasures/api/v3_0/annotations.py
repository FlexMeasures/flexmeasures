"""
API endpoints for annotations.
"""

from flask import current_app
from flask_classful import FlaskView, route
from flask_security import current_user, auth_required
from webargs.flaskparser import use_kwargs, use_args
from werkzeug.exceptions import InternalServerError
from sqlalchemy.exc import SQLAlchemyError

from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db
from flexmeasures.data.models.annotations import Annotation, get_or_create_annotation
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import Account
from flexmeasures.data.schemas import AssetIdField, SensorIdField
from flexmeasures.data.schemas.account import AccountIdField
from flexmeasures.data.schemas.annotations import (
    AnnotationSchema,
    AnnotationResponseSchema,
)
from flexmeasures.data.services.data_sources import get_or_create_source


annotation_schema = AnnotationSchema()
annotation_response_schema = AnnotationResponseSchema()


class AnnotationAPI(FlaskView):
    """
    This view exposes annotation creation through API endpoints.
    """

    route_base = "/annotation"
    trailing_slash = False
    decorators = [auth_required()]

    @route("/accounts/<id>", methods=["POST"])
    @use_kwargs({"account": AccountIdField(data_key="id")}, location="path")
    @use_args(annotation_schema)
    @permission_required_for_context("create-children", ctx_arg_name="account")
    def post_account_annotation(self, annotation_data: dict, id: int, account: Account):
        """
        .. :quickref: Annotations; Add an annotation to an account.
        ---
        post:
          summary: Creates a new account annotation.
          description: |
            This endpoint creates a new annotation on an account.

          security:
            - ApiKeyAuth: []
          requestBody:
            content:
              application/json:
                schema: AnnotationSchema
          responses:
            200:
              description: ALREADY PROCESSED
            201:
              description: PROCESSED
            400:
              description: INVALID_REQUEST
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Annotations
        """
        return self._create_annotation(annotation_data, account=account)

    @route("/assets/<id>", methods=["POST"])
    @use_kwargs({"asset": AssetIdField(data_key="id")}, location="path")
    @use_args(annotation_schema)
    @permission_required_for_context("create-children", ctx_arg_name="asset")
    def post_asset_annotation(
        self, annotation_data: dict, id: int, asset: GenericAsset
    ):
        """.. :quickref: Annotations; Add an annotation to an asset.
        ---
        post:
          summary: Creates a new asset annotation.
          description: |
            This endpoint creates a new annotation on an asset.

          security:
            - ApiKeyAuth: []
          requestBody:
            content:
              application/json:
                schema: AnnotationSchema
          responses:
            200:
              description: ALREADY PROCESSED
            201:
              description: PROCESSED
            400:
              description: INVALID_REQUEST
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Annotations
        """
        return self._create_annotation(annotation_data, asset=asset)

    @route("/sensors/<id>", methods=["POST"])
    @use_kwargs({"sensor": SensorIdField(data_key="id")}, location="path")
    @use_args(annotation_schema)
    @permission_required_for_context("create-children", ctx_arg_name="sensor")
    def post_sensor_annotation(self, annotation_data: dict, id: int, sensor: Sensor):
        """.. :quickref: Annotations; Add an annotation to a sensor.
        ---
        post:
          summary: Creates a new sensor annotation.
          description: |
            This endpoint creates a new annotation on a sensor.

          security:
            - ApiKeyAuth: []
          requestBody:
            content:
              application/json:
                schema: AnnotationSchema
          responses:
            200:
              description: ALREADY PROCESSED
            201:
              description: PROCESSED
            400:
              description: INVALID_REQUEST
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Annotations
        """
        return self._create_annotation(annotation_data, sensor=sensor)

    def _create_annotation(
        self,
        annotation_data: dict,
        account: Account | None = None,
        asset: GenericAsset | None = None,
        sensor: Sensor | None = None,
    ):
        """Create an annotation and link it to the specified entity.

        Returns:
            - 201 Created for new annotations
            - 200 OK for existing annotations (idempotent behavior)
        """
        try:
            # Get or create data source for current user
            source = get_or_create_source(current_user)

            # Create annotation object
            annotation = Annotation(
                content=annotation_data["content"],
                start=annotation_data["start"],
                end=annotation_data["end"],
                type=annotation_data.get("type", "label"),
                belief_time=annotation_data.get("belief_time"),
                source=source,
            )

            # Use get_or_create to handle duplicates gracefully
            annotation, is_new = get_or_create_annotation(annotation)

            # Link annotation to entity
            if account is not None:
                if annotation not in account.annotations:
                    account.annotations.append(annotation)
            elif asset is not None:
                if annotation not in asset.annotations:
                    asset.annotations.append(annotation)
            elif sensor is not None:
                if annotation not in sensor.annotations:
                    sensor.annotations.append(annotation)

            db.session.commit()

            # Return appropriate status code
            status_code = 201 if is_new else 200
            return annotation_response_schema.dump(annotation), status_code

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Database error while creating annotation: {e}")
            raise InternalServerError(
                "A database error occurred while creating the annotation"
            )
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Unexpected error creating annotation: {e}")
            raise InternalServerError(
                "An unexpected error occurred while creating the annotation"
            )
