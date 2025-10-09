from marshmallow import Schema, fields


def make_openapi_compatible(schema_cls: type[Schema]) -> type[Schema]:
    """
    Create an OpenAPI-compatible version of a Marshmallow schema.

    - Drops custom __init__ args from the original schema
    - Replaces custom fields (like VariableQuantityField) with String
    """

    new_fields = {}
    for name, field in schema_cls._declared_fields.items():
        # Keep only standard marshmallow fields
        if field.__module__.startswith("marshmallow.fields"):
            new_fields[name] = field
        else:
            # Replace *any* non-standard field (like VariableQuantityField) with OpenAPI compatible String field
            # Adding description so the user knows what the actual field is
            new_fields[name] = fields.String()

    # Build schema dynamically, based only on safe fields
    openAPI_schema = type(
        f"{schema_cls.__name__}OpenAPI",
        (Schema,),
        new_fields,
    )
    return openAPI_schema
