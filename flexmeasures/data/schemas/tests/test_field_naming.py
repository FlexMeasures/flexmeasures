"""Field names on the wire are kebab-case.

The API is moving to kebab-case throughout (see issue #2540), and the way that stalls is not
a decision to reverse it but a field added in the old style while nobody is looking.
These tests hold the line: the debt is listed, and the list may only shrink.
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
        "df_input",
        "df_output",
        "end_time",
        "entity_address",
        "event_ends_before",
        "event_resolution",
        "event_starts_after",
        "exclude_source_types",
        "external_id",
        "flex_context",
        "flex_model",
        "flexmeasures_roles",
        "generic_asset_id",
        "generic_asset_type",
        "generic_asset_type_id",
        "horizons_at_least",
        "horizons_at_most",
        "include_consultancy_clients",
        "include_inactive",
        "include_public",
        "include_public_assets",
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
        "secondary_color",
        "sensors_to_show",
        "sensors_to_show_as_kpis",
        "skip_if_empty",
        "source_account_ids",
        "source_types",
        "staleness_search",
        "start_time",
        "sum_multiple",
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


def test_the_list_of_known_snake_case_names_has_no_stale_entries(wire_names):
    """An entry stays only while the field it excuses is still spelled that way.

    Without this the list would quietly outlive the debt it records, and stop being a measure of it.
    """
    stale = sorted(KNOWN_SNAKE_CASE_WIRE_NAMES - set(wire_names))

    assert not stale, (
        "these names are excused but no longer on the wire, so drop them from"
        f" KNOWN_SNAKE_CASE_WIRE_NAMES:\n  {', '.join(stale)}"
    )
