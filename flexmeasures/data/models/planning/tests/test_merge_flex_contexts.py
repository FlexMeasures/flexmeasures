"""Tests for merging a passed flex-context with the one stored on an asset."""

import pytest

from flexmeasures.data.models.planning import (
    TOP_LEVEL_FLEX_CONTEXT_KEYS,
    merge_flex_contexts,
)
from flexmeasures.data.schemas.scheduling import (
    CommodityFlexContextSchema,
    FlexContextSchema,
)

STORED = {"site-power-capacity": "1 MVA", "consumption-price": "100 EUR/MWh"}
GAS = {"commodity": "gas", "consumption-price": "50 EUR/MWh"}


def test_electricity_only_flex_contexts_merge_field_by_field():
    assert merge_flex_contexts(STORED, {"consumption-price": "80 EUR/MWh"}) == {
        "site-power-capacity": "1 MVA",
        "consumption-price": "80 EUR/MWh",
    }


@pytest.mark.parametrize(
    "passed",
    [
        # As passed to the scheduler directly, e.g. by `flexmeasures add schedule`
        [{"commodity": "electricity", "consumption-price": "80 EUR/MWh"}, GAS],
        # As the API passes on a list
        {
            "commodities": [
                {"commodity": "electricity", "consumption-price": "80 EUR/MWh"},
                GAS,
            ]
        },
        # With the electricity fields at the top level
        {"consumption-price": "80 EUR/MWh", "commodities": [GAS]},
    ],
)
def test_stored_fields_count_for_the_passed_electricity_context(passed):
    """Whatever form the passed flex-context takes, the stored fields end up in its electricity context, where the passed fields take precedence."""
    assert merge_flex_contexts(STORED, passed) == {
        "commodities": [
            {
                "commodity": "electricity",
                "site-power-capacity": "1 MVA",
                "consumption-price": "80 EUR/MWh",
            },
            GAS,
        ]
    }


def test_passed_electricity_context_takes_precedence_over_passed_top_level():
    passed = {
        "consumption-price": "80 EUR/MWh",
        "site-consumption-breach-price": "5000 EUR/kW",
        "commodities": [
            {"commodity": "electricity", "consumption-price": "90 EUR/MWh"},
        ],
    }
    assert merge_flex_contexts({}, passed) == {
        "commodities": [
            {
                "commodity": "electricity",
                "consumption-price": "90 EUR/MWh",
                "site-consumption-breach-price": "5000 EUR/kW",
            },
        ]
    }


def test_stored_commodity_contexts_merge_per_commodity():
    """A stored commodity context is merged with the passed context for the same commodity, or else kept as is."""
    stored = {
        **STORED,
        "commodities": [
            {"commodity": "gas", "site-power-capacity": "2 MVA"},
            {"commodity": "heat", "consumption-price": "10 EUR/MWh"},
        ],
    }
    assert merge_flex_contexts(stored, [GAS]) == {
        "commodities": [
            {
                "commodity": "gas",
                "site-power-capacity": "2 MVA",
                "consumption-price": "50 EUR/MWh",
            },
            {"commodity": "electricity", **STORED},
            {"commodity": "heat", "consumption-price": "10 EUR/MWh"},
        ]
    }


def test_top_level_only_fields_stay_at_the_top_level():
    stored = {**STORED, "aggregate-power": {"sensor": 1}}
    passed = {
        "commitments": [{"name": "a commitment", "baseline": "0 kW"}],
        "commodities": [GAS],
    }
    merged = merge_flex_contexts(stored, passed)
    assert merged["aggregate-power"] == {"sensor": 1}
    assert merged["commitments"] == passed["commitments"]
    assert all(
        "aggregate-power" not in context and "commitments" not in context
        for context in merged["commodities"]
    )


def test_passed_inflexible_device_keys_shadow_the_stored_ones():
    stored = {**STORED, "inflexible-device-sensors": [1]}
    passed = [{"commodity": "electricity", "inflexible-consumption": [{"sensor": 2}]}]
    (electricity,) = merge_flex_contexts(stored, passed)["commodities"]
    assert "inflexible-device-sensors" not in electricity
    assert electricity["inflexible-consumption"] == [{"sensor": 2}]


def test_top_level_flex_context_keys_match_the_schemas():
    """The fields that only exist at the top level, plus the top-level commitments, which each name their own commodity."""

    def data_keys(schema) -> set[str]:
        return {
            field.data_key or name for name, field in schema.declared_fields.items()
        }

    top_level_only = data_keys(FlexContextSchema()) - data_keys(
        CommodityFlexContextSchema()
    )
    assert TOP_LEVEL_FLEX_CONTEXT_KEYS == (top_level_only - {"commodities"}) | {
        "commitments"
    }
