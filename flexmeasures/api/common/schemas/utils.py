from copy import copy
from typing import Type, cast

from marshmallow import Schema, fields

from flexmeasures.data.schemas.scheduling import rst_to_openapi
from flexmeasures.data.schemas.sensors import (
    VariableQuantityField,
    VariableQuantityOpenAPISchema,
)


def make_openapi_compatible(schema_cls: Type[Schema]) -> Type[Schema]:
    """
    Create an OpenAPI-compatible version of a Marshmallow schema.

    - Drops custom __init__ args from the original schema
    - Replaces custom fields (like VariableQuantityField) with String
    """

    new_fields = {}
    for name, field in schema_cls._declared_fields.items():

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

            field_copy = fields.Nested(
                VariableQuantityOpenAPISchema,
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
