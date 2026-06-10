"""Tests for the static OpenAPI specification file."""

import json
from pathlib import Path


OPENAPI_SPEC_PATH = Path("flexmeasures/ui/static/openapi-specs.json")

# Python type names that are commonly confused with their JSON Schema equivalents.
# Keyed by the wrong value, valued by the correct replacement.
PYTHON_TYPE_ALIASES = {
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "dict": "object",
    "list": "array",
    "str": "string",
    "bytes": "string",
    "tuple": "array",
}


def _collect_type_values(node, path=""):
    """Yield (json_path, type_value) for every 'type' key found anywhere in *node*."""
    if isinstance(node, dict):
        if "type" in node:
            yield path + ".type", node["type"]
        for key, value in node.items():
            yield from _collect_type_values(value, path + f".{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _collect_type_values(item, path + f"[{i}]")


def test_openapi_spec_schema_types_are_not_python_aliases():
    """No 'type' declaration in openapi-specs.json may use a Python type alias.

    Catches typos that silently break Swagger UI field rendering,
    such as ``type: int`` (Python) instead of ``type: integer`` (JSON Schema).
    See: https://swagger.io/docs/specification/data-models/data-types/
    """
    spec = json.loads(OPENAPI_SPEC_PATH.read_text())

    invalid = []
    for json_path, type_value in _collect_type_values(spec):
        # type can be a string or a list of strings (OpenAPI 3.1 nullable shorthand).
        # Non-string values (e.g. nested schema objects) are skipped.
        type_values = type_value if isinstance(type_value, list) else [type_value]
        for tv in type_values:
            if isinstance(tv, str) and tv in PYTHON_TYPE_ALIASES:
                invalid.append((json_path, tv, PYTHON_TYPE_ALIASES[tv]))

    assert not invalid, (
        "The following 'type' values in openapi-specs.json use Python type aliases "
        "instead of JSON Schema types:\n\n"
        + "\n".join(
            f"  {path!r}: {wrong!r}  (use {correct!r} instead)"
            for path, wrong, correct in invalid
        )
    )
