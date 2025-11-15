import re

from marshmallow import Schema, fields


def rst_to_openapi(text: str) -> str:
    """
    Convert a string with RST markup to OpenAPI-safe text.

    - Replaces :abbr:`X (Y)` with <abbr title="Y">X</abbr>
    """

    def abbr_repl(match):
        content = match.group(1)
        if "(" in content and content.endswith(")"):
            abbr, title = content.split("(", 1)
            title = title[:-1]  # remove closing parenthesis
            return f'<abbr title="{title.strip()}">{abbr.strip()}</abbr>'
        else:
            return content

    # Replace all :abbr:`...` directives
    return re.sub(r":abbr:`([^`]+)`", abbr_repl, text)


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
            # Replace *any* non-standard field (like VariableQuantityField) with OpenAPI compatible String field,

            # Copy metadata, but sanitize description for OpenAPI
            metadata = dict(field.metadata)  # make a shallow copy
            if "description" in metadata:
                metadata["description"] = rst_to_openapi(metadata["description"])

            # Copy its name and metadata so the user knows what the actual field is and what it's for
            new_fields[name] = fields.String(metadata=metadata)

    # Build schema dynamically, based only on safe fields
    openAPI_schema = type(
        f"{schema_cls.__name__}OpenAPI",
        (Schema,),
        new_fields,
    )
    return openAPI_schema
