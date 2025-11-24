import re
from typing import Type, cast

from marshmallow import Schema, fields

from flexmeasures.data.schemas.sensors import (
    VariableQuantityField,
    VariableQuantityOpenAPISchema,
)


def rst_to_openapi(text: str) -> str:
    """
    Convert a string with RST markup to OpenAPI-safe text.

    - Replaces :abbr:`X (Y)` with <abbr title="Y">X</abbr>
    - Converts :math:`base^{exp}` into HTML sup/sub notation for OpenAPI
    """

    # Handle abbreviations
    def abbr_repl(match):
        content = match.group(1)
        if "(" in content and content.endswith(")"):
            abbr, title = content.split("(", 1)
            title = title[:-1]
            return f'<abbr title="{title.strip()}">{abbr.strip()}</abbr>'
        else:
            return content

    text = re.sub(r":abbr:`([^`]+)`", abbr_repl, text)

    # Handle math
    def math_repl(match):
        expr = match.group(1).strip()

        # simple power pattern: base^{exp}
        power_match = re.match(r"(.+?)\s*\^\s*\{(.+?)\}", expr)
        if power_match:
            base, exponent = power_match.groups()
            return f"{base}<sup>{exponent}</sup>"

        # fallback: drop :math:`...` wrapper and return raw content
        return expr

    text = re.sub(r":math:`([^`]+)`", math_repl, text)

    return text


def make_openapi_compatible(schema_cls: Type[Schema]) -> Type[Schema]:
    """
    Create an OpenAPI-compatible version of a Marshmallow schema.

    - Drops custom __init__ args from the original schema
    - Replaces custom fields (like VariableQuantityField) with String
    """

    new_fields = {}
    for name, field in schema_cls._declared_fields.items():
        # Keep only standard marshmallow fields
        new_fields[name] = field

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
            new_fields[name] = field_copy

    # Build schema dynamically, based only on safe fields
    openAPI_schema = type(
        f"{schema_cls.__name__}OpenAPI",
        (Schema,),
        new_fields,
    )
    return cast(Type[Schema], openAPI_schema)
