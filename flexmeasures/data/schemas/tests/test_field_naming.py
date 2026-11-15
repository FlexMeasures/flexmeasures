"""Field names on the wire are kebab-case.

The API is moving to kebab-case throughout (see issue #2540), and the way that stalls is not
a decision to reverse it but a field added in the old style while nobody is looking.
These tests hold the line: the debt is listed, and the list may only shrink.

Names are checked in two places.
The Marshmallow schemas FlexMeasures defines are where most fields are declared.
The published OpenAPI specs catch what those schemas cannot show,
such as a parameter declared inline in `use_kwargs({...})`, whose schema Marshmallow generates in its own module,
or a response field documented on an endpoint rather than declared in a schema.
"""

from __future__ import annotations

import importlib
import pkgutil
import warnings

import pytest
from marshmallow import Schema

# Wire names that predate the move to kebab-case. Each has shipped, so renaming one is the
# two-step transition in #2540 rather than an edit: accept both spellings on the way in and
# return both on the way out, then drop the old one in a new API version.
#
# Removing an entry as a field is renamed is expected and welcome. Adding one is not:
# a new field spelled with an underscore should be spelled with a dash instead.
KNOWN_SNAKE_CASE_WIRE_NAMES = frozenset(
    {
        "account_id",
        "account_roles",
        "active_user_id",
        "authentication_token",
        "all_accessible",
        "asset_type",
        "belief_horizon",
        "belief_time",
        "beliefs_after",
        "beliefs_before",
        "check_output_resolution",
        "child_assets",
        "consultancy_account_id",
        "consumption_price_sensor",
        "database_redis",
        "database_sql",
        "default_asset_view",
        "df_input",
        "df_output",
        "ended_at",
        "enqueued_at",
        "end_time",
        "entity_address",
        "event_datetime",
        "event_end_time",
        "event_ends_before",
        "event_resolution",
        "event_start_time",
        "event_starts_after",
        "exc_info",
        "exclude_source_types",
        "external_id",
        "flex_context",
        "flex_model",
        "flexmeasures_roles",
        "flexmeasures_version",
        "func_name",
        "generic_asset_id",
        "generic_asset_type",
        "generic_asset_type_id",
        "horizons_at_least",
        "horizons_at_most",
        "include_consultancy_clients",
        "include_inactive",
        "include_public",
        "include_public_assets",
        "keep_legends_below_graphs",
        "last_login_at",
        "last_seen_at",
        "logo_url",
        "loss_is_positive",
        "max_future_staleness",
        "max_staleness",
        "most_recent_beliefs_only",
        "most_recent_events_only",
        "most_recent_only",
        "one_deterministic_belief_per_event",
        "one_deterministic_belief_per_event_per_source",
        "only_latest",
        "parent_asset_id",
        "plan_id",
        "primary_color",
        "production_price_sensor",
        "required_input",
        "required_output",
        "scheduler_info",
        "secondary_color",
        "sensors_to_show",
        "sensors_to_show_as_kpis",
        "skip_if_empty",
        "source_account_ids",
        "source_types",
        "staleness_search",
        "start_time",
        "started_at",
        "sum_multiple",
        "use_as_default",
        "use_latest_version_only",
        "use_latest_version_per_event",
        "user_source_ids",
    }
)


def _flexmeasures_schemas() -> list[type[Schema]]:
    """Every Marshmallow schema FlexMeasures defines, found by importing and walking subclasses."""
    for package in ("flexmeasures.data.schemas", "flexmeasures.api"):
        module = importlib.import_module(package)
        for found in pkgutil.walk_packages(module.__path__, package + "."):
            if ".tests" in found.name:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    importlib.import_module(found.name)
                except Exception:
                    # A module that cannot be imported here cannot contribute a field name either.
                    continue

    seen: set[type[Schema]] = set()

    def walk(cls: type[Schema]):
        for subclass in cls.__subclasses__():
            if subclass not in seen:
                seen.add(subclass)
                walk(subclass)

    walk(Schema)
    return [cls for cls in seen if cls.__module__.startswith("flexmeasures")]


def _wire_names() -> dict[str, set[str]]:
    """Map each name a schema puts on the wire to the schemas that put it there.

    A field's wire name is its `data_key` where it sets one, and its attribute name otherwise.
    """
    names: dict[str, set[str]] = {}
    for cls in _flexmeasures_schemas():
        try:
            fields = cls().fields
        except Exception:
            # Schemas that need arguments to instantiate are covered through the ones that use them.
            continue
        for attribute, field in fields.items():
            names.setdefault(field.data_key or attribute, set()).add(
                f"{cls.__module__}.{cls.__name__}"
            )
    return names


def _cli_option_names() -> dict[str, set[str]]:
    """Map each command-line option a schema field declares to the schemas declaring it."""
    options: dict[str, set[str]] = {}
    for cls in _flexmeasures_schemas():
        try:
            fields = cls().fields
        except Exception:
            continue
        for field in fields.values():
            option = ((field.metadata or {}).get("cli") or {}).get("option")
            if option:
                options.setdefault(option, set()).add(
                    f"{cls.__module__}.{cls.__name__}"
                )
    return options


def _openapi_specs() -> dict:
    """The published OpenAPI specs, which the pre-commit hook regenerates from the endpoints' docstrings and schemas."""
    import json
    from importlib.resources import files

    return json.loads(
        files("flexmeasures.ui").joinpath("static/openapi-specs.json").read_text()
    )


def _openapi_parameter_names(specs: dict) -> dict[str, set[str]]:
    """Map each query, header or cookie parameter the specs name to the operations taking it.

    Path parameters are left to their own test, as Flask cannot name a route variable with a dash.
    """
    names: dict[str, set[str]] = {}
    for path, operations in specs["paths"].items():
        for method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            for parameter in operation.get("parameters", []):
                if parameter.get("in") != "path":
                    names.setdefault(parameter["name"], set()).add(
                        f"{method.upper()} {path}"
                    )
    return names


def _openapi_property_names(specs: dict) -> dict[str, set[str]]:
    """Map each property of a request or response body the specs describe to where it is described."""
    names: dict[str, set[str]] = {}

    def walk(node, where: str):
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                for name in properties:
                    names.setdefault(name, set()).add(where)
            for value in node.values():
                walk(value, where)
        elif isinstance(node, list):
            for value in node:
                walk(value, where)

    for path, operations in specs["paths"].items():
        walk(operations, path)
    for name, schema in specs.get("components", {}).get("schemas", {}).items():
        walk(schema, f"#/components/schemas/{name}")
    return names


@pytest.fixture(scope="module")
def openapi_names() -> dict[str, set[str]]:
    """Every parameter and body property the published specs name, mapped to where they name it."""
    specs = _openapi_specs()
    names = _openapi_parameter_names(specs)
    for name, places in _openapi_property_names(specs).items():
        names.setdefault(name, set()).update(places)
    return names


@pytest.fixture(scope="module")
def wire_names(app) -> dict[str, set[str]]:
    """Importing the schema modules needs an application context."""
    with app.app_context():
        return _wire_names()


@pytest.fixture(scope="module")
def cli_option_names(app) -> dict[str, set[str]]:
    with app.app_context():
        return _cli_option_names()


def test_a_field_on_the_wire_is_kebab_case(wire_names):
    """A new field is spelled with dashes, not underscores.

    Set `data_key` where the attribute name cannot be, as Python attributes cannot hold a dash.
    """
    offenders = {
        name: sorted(schemas)
        for name, schemas in wire_names.items()
        if "_" in name and name not in KNOWN_SNAKE_CASE_WIRE_NAMES
    }

    assert not offenders, (
        "these field names reach the wire with an underscore:\n"
        + "\n".join(
            f"  {name}: {', '.join(schemas)}"
            for name, schemas in sorted(offenders.items())
        )
        + "\n\nSpell them with dashes, giving the field a `data_key` where its attribute name cannot be."
    )


def test_a_command_line_option_is_kebab_case(cli_option_names):
    """The same rule, for the options a schema field declares.

    Schemas are shared between the API and the CLI, so a field often names both,
    and the two should read the same way.
    """
    offenders = {
        option: sorted(schemas)
        for option, schemas in cli_option_names.items()
        if "_" in option
    }

    assert (
        not offenders
    ), "these command-line options carry an underscore:\n" + "\n".join(
        f"  {option}: {', '.join(schemas)}"
        for option, schemas in sorted(offenders.items())
    )


def test_the_list_of_known_snake_case_names_has_no_stale_entries(
    wire_names, openapi_names
):
    """An entry stays only while the field it excuses is still spelled that way, in a schema or in the published specs.

    Without this the list would quietly outlive the debt it records, and stop being a measure of it.
    """
    stale = sorted(KNOWN_SNAKE_CASE_WIRE_NAMES - set(wire_names) - set(openapi_names))

    assert not stale, (
        "these names are excused but no longer on the wire, so drop them from"
        f" KNOWN_SNAKE_CASE_WIRE_NAMES:\n  {', '.join(stale)}"
    )


def test_a_path_parameter_in_the_openapi_specs_is_kebab_case():
    """The same rule, for the path parameters the published specs name, such as the automation-id in the automation endpoints' paths.

    Flask cannot name a route variable with a dash, so the specs spell it in kebab-case where the route keeps its underscore.
    """
    import json
    import re
    from importlib.resources import files

    specs = json.loads(
        files("flexmeasures.ui").joinpath("static/openapi-specs.json").read_text()
    )
    offenders = sorted(
        path
        for path in specs["paths"]
        if any("_" in name for name in re.findall(r"{([^{}]+)}", path))
    )
    declared = sorted(
        {
            parameter["name"]
            for operations in specs["paths"].values()
            for operation in operations.values()
            if isinstance(operation, dict)
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path" and "_" in parameter.get("name", "")
        }
    )

    assert (
        not offenders
    ), "these paths have a path parameter with an underscore:\n  " + "\n  ".join(
        offenders
    )
    assert (
        not declared
    ), "these path parameters are declared with an underscore:\n  " + "\n  ".join(
        declared
    )


def test_a_query_parameter_in_the_openapi_specs_is_kebab_case():
    """The same rule, for the query, header and cookie parameters the published specs name.

    Endpoints often declare these inline, as in `@use_kwargs({"asset": AssetIdField(data_key="asset")}, location="query")`,
    and Marshmallow generates the schema for such a dict in its own module, out of reach of the test on schemas.
    """
    offenders = {
        name: sorted(operations)
        for name, operations in _openapi_parameter_names(_openapi_specs()).items()
        if "_" in name and name not in KNOWN_SNAKE_CASE_WIRE_NAMES
    }

    assert not offenders, (
        "these parameters are named with an underscore in the OpenAPI specs:\n"
        + "\n".join(
            f"  {name}: {', '.join(operations)}"
            for name, operations in sorted(offenders.items())
        )
        + "\n\nSpell them with dashes, giving the field a `data_key` where its attribute name cannot be."
    )


def test_a_body_property_in_the_openapi_specs_is_kebab_case():
    """The same rule, for the request and response body properties the published specs describe.

    This catches a response field documented on its endpoint, whose payload is built as a plain dict rather than dumped by a schema.
    """
    offenders = {
        name: sorted(places)
        for name, places in _openapi_property_names(_openapi_specs()).items()
        if "_" in name and name not in KNOWN_SNAKE_CASE_WIRE_NAMES
    }

    assert not offenders, (
        "these body properties are named with an underscore in the OpenAPI specs:\n"
        + "\n".join(
            f"  {name}: {', '.join(places)}"
            for name, places in sorted(offenders.items())
        )
        + "\n\nSpell them with dashes."
    )
