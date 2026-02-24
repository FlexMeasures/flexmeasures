from copy import copy
from typing import Type, cast

from marshmallow import Schema, fields

from flexmeasures.utils.doc_utils import rst_to_openapi
from flexmeasures.data.schemas.forecasting.pipeline import (
    ForecastingTriggerSchema,
    TrainPredictPipelineConfigSchema,
)
from flexmeasures.data.schemas.sensors import (
    SensorReferenceSchema,
    VariableQuantityField,
    VariableQuantityOpenAPISchema,
)


def make_openapi_compatible(schema_cls: Type[Schema]) -> Type[Schema]:  # noqa: C901
    """
    Create an OpenAPI-compatible version of a Marshmallow schema.

    - Drops custom __init__ args from the original schema
    - Replaces custom fields (like VariableQuantityField) with String
    """

    sensor_only_validators = []
    for validator in schema_cls._hooks["validates"]:
        if "is_sensor" in validator[0]:
            sensor_only_validators.append(validator[-1])

    new_fields = {}
    for name, field in schema_cls._declared_fields.items():

        if schema_cls in (ForecastingTriggerSchema, TrainPredictPipelineConfigSchema):
            if "cli" in field.metadata and field.metadata["cli"].get(
                "cli-exclusive", False
            ):
                continue
            if isinstance(field, fields.Nested):
                nested_schema_cls = type(field.schema)
                if nested_schema_cls is TrainPredictPipelineConfigSchema:
                    field_copy = fields.Nested(
                        make_openapi_compatible(nested_schema_cls),
                        metadata=field.metadata,
                        data_key=field.data_key,
                        many=field.many,
                        required=field.required,
                        allow_none=field.allow_none,
                    )
                    new_fields[name] = field_copy
                    continue

        # Copy metadata, but sanitize description for OpenAPI
        metadata = dict(getattr(field, "metadata", {}))
        if "description" in metadata:
            metadata["description"] = rst_to_openapi(metadata["description"])

        # Replace VariableQuantityField with OpenAPI compatible String field
        if isinstance(field, VariableQuantityField):

            # Copy metadata, but sanitize description for OpenAPI
            metadata = dict(field.metadata)  # make a shallow copy
            if "description" in metadata:
                metadata["description"] = rst_to_openapi(metadata["description"])

            sensor_only = False
            for validator in sensor_only_validators:
                if "field_name" in validator and validator["field_name"] == name:
                    # Marshmallow 4 uses "field_name" in its "validates" hooks
                    sensor_only = True
                elif "field_names" in validator and name in validator["field_names"]:
                    # Marshmallow 4 uses "field_names" in its "validates" hooks
                    sensor_only = True
            if sensor_only:
                oapi_schema = SensorReferenceSchema
            else:
                oapi_schema = VariableQuantityOpenAPISchema
            field_copy = fields.Nested(
                oapi_schema,
                metadata=metadata,
                data_key=field.data_key,
            )
        else:
            # For other fields, just copy with sanitized metadata
            field_copy = copy(field)
            field_copy.metadata = metadata
        new_fields[name] = field_copy

    # Build schema dynamically, based only on safe fields
    openAPI_schema = type(
        f"{schema_cls.__name__}OpenAPI",
        (Schema,),
        new_fields,
    )
    return cast(Type[Schema], openAPI_schema)
