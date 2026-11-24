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
        # With the electricity fields at the top level, next to a listed electricity context
        {
            "consumption-price": "80 EUR/MWh",
            "commodities": [{"commodity": "electricity"}, GAS],
        },
    ],
)
def test_stored_fields_count_for_the_passed_electricity_context(passed):
    """Whatever form the passed flex-context takes, if it has an electricity context, the stored fields end up in it, where the passed fields take precedence."""
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


@pytest.mark.parametrize(
    "stored, passed, expected",
    [
        # As the API passes on a list without an electricity context
        (
            STORED,
            {"commodities": [GAS]},
            {**STORED, "commodities": [GAS]},
        ),
        # Electricity fields at the top level of both flex-contexts
        (
            STORED,
            {"consumption-price": "80 EUR/MWh", "commodities": [GAS]},
            {
                "site-power-capacity": "1 MVA",
                "consumption-price": "80 EUR/MWh",
                "commodities": [GAS],
            },
        ),
        # An asset with commodity tabs in the UI, passed a flex-context describing only electricity
        (
            {**STORED, "commodities": [GAS]},
            {"consumption-price": "80 EUR/MWh"},
            {
                "site-power-capacity": "1 MVA",
                "consumption-price": "80 EUR/MWh",
                "commodities": [GAS],
            },
        ),
    ],
)
def test_top_level_stays_the_electricity_context_if_none_is_listed(
    stored, passed, expected
):
    """Without a listed electricity context, the top level keeps serving as the electricity context, so it keeps the semantics of a top-level flex-context.

    Folding it into a commodity context would give it the defaults for a commodity context that sets only some grid-connection fields
    (e.g. a zero site production capacity, if only a consumption price is set).
    """
    assert merge_flex_contexts(stored, passed) == expected


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
        "commodities": [{"commodity": "electricity"}, GAS],
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


@pytest.mark.parametrize(
    "passed",
    [
        [{"commodity": "electricity", "commitments": [{"name": "passed"}]}],
        {"commitments": [{"name": "passed"}], "commodities": [GAS]},
    ],
)
def test_passed_electricity_commitments_replace_the_stored_ones(passed):
    """Commitments passed for electricity replace the stored top-level ones, as they do in a flex-context describing only electricity."""
    stored = {**STORED, "commitments": [{"name": "stored"}]}
    merged = merge_flex_contexts(stored, passed)
    all_commitments = merged.get("commitments", []) + [
        commitment
        for context in merged["commodities"]
        for commitment in context.get("commitments", [])
    ]
    assert all_commitments == [{"name": "passed"}]


def test_top_level_flex_context_keys_match_the_schemas():
    """The fields that stay at the top level are those that only exist there, plus the top-level commitments, which each name their own commodity.

    The exceptions are the deprecated price sensors, which describe the prices of electricity.
    """

    def data_keys(schema) -> set[str]:
        return {
            field.data_key or name for name, field in schema.declared_fields.items()
        }

    top_level_only = data_keys(FlexContextSchema()) - data_keys(
        CommodityFlexContextSchema()
    )
    assert TOP_LEVEL_FLEX_CONTEXT_KEYS == (
        top_level_only
        - {"commodities", "consumption-price-sensor", "production-price-sensor"}
    ) | {"commitments"}
