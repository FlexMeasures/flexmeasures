"""Tests for flexmeasures/ui/static/js/flex-context-utils.js, used by the flex-context editor."""

# A few fields in the shape of UI_FLEX_CONTEXT_SCHEMA (see flexmeasures/data/schemas/scheduling/__init__.py).
SCHEMA = """
const schemaSpecs = {
    "consumption-price": {"default": null, "types": {"backend": "typeOne"}, "per-commodity": true},
    "site-power-capacity": {"default": null, "types": {"backend": "typeOne"}},
    "aggregate-power": {"default": null, "types": {"backend": "typeTwo"}},
    "inflexible-consumption": {"default": [], "types": {"backend": "typeFour"}},
    "commitments": {"default": [], "types": {"backend": "typeFive"}, "per-commodity": true},
};
const schema = Object.fromEntries(Object.entries(schemaSpecs).map(([key, spec]) => [key, spec.default]));
"""


def test_field_kinds(assert_js):
    assert_js(SCHEMA + """
        import { isSensorOnlyField, isSensorListField } from "/js/flex-context-utils.js";
        eq("a field taking a sensor or a value offers both",
           isSensorOnlyField(schemaSpecs, "consumption-price"), false);
        eq("a single sensor reference is sensor-only", isSensorOnlyField(schemaSpecs, "aggregate-power"), true);
        eq("so is a list of sensors", isSensorOnlyField(schemaSpecs, "inflexible-consumption"), true);
        eq("only the list is a list", [isSensorListField(schemaSpecs, "aggregate-power"),
                                        isSensorListField(schemaSpecs, "inflexible-consumption")], [false, true]);
        eq("an unknown field is neither", [isSensorOnlyField(schemaSpecs, "nope"), isSensorListField(schemaSpecs, "nope")],
           [false, false]);
        """)


def test_entry_sensor_id(assert_js):
    assert_js("""
        import { entrySensorId } from "/js/flex-context-utils.js";
        eq("a sensor reference", entrySensorId({sensor: 5, source: 2}), 5);
        eq("a bare id, as the deprecated field held", entrySensorId(5), 5);
        eq("nothing", entrySensorId(null), null);
        """)


def test_fields_available_per_commodity(assert_js):
    """The top level takes every field, a commodity context only the per-commodity ones."""
    assert_js(SCHEMA + """
        import { isFieldAvailableInScope, isStructuralField, getActiveContext } from "/js/flex-context-utils.js";
        eq("the top level takes any field", isFieldAvailableInScope(schemaSpecs, "site-power-capacity", null), true);
        eq("a commodity does not take a site-wide field", isFieldAvailableInScope(schemaSpecs, "site-power-capacity", 0), false);
        eq("but does take a per-commodity field", isFieldAvailableInScope(schemaSpecs, "consumption-price", 0), true);
        eq("the commodity tab bar's own fields are never cards",
           ["commodities", "commodity"].map((f) => isFieldAvailableInScope(schemaSpecs, f, null)), [false, false]);
        eq("because they are structural", ["commodities", "commodity", "commitments"].map(isStructuralField), [true, true, false]);

        const flexContext = {"site-power-capacity": "1 MW", commodities: [{commodity: "gas"}]};
        eq("the top level is the flex-context itself", getActiveContext(flexContext, null), flexContext);
        eq("a commodity is one entry of its list", getActiveContext(flexContext, 0), {commodity: "gas"});
        """)


def test_clean_flex_context_before_saving(assert_js):
    assert_js(SCHEMA + """
        import { cleanFlexContext } from "/js/flex-context-utils.js";
        const flexContext = {
            "site-power-capacity": "1 MW",
            "consumption-price": "",
            "inflexible-consumption": [],
            "aggregate-power": null,
            "not-a-field": "x",
            "commodity": "electricity",
            "commodities": [
                {"commodity": "gas", "consumption-price": "30 EUR/MWh", "commitments": [], "not-a-field": 1},
            ],
        };
        const cleaned = cleanFlexContext(flexContext, schema);
        eq("empty and unknown fields are dropped, the structure is kept", cleaned, {
            "site-power-capacity": "1 MW",
            "commodities": [{"commodity": "gas", "consumption-price": "30 EUR/MWh"}],
        });
        check("the flex-context is cleaned in place", cleaned === flexContext);
        eq("an empty list of commodities goes too", cleanFlexContext({commodities: []}, schema), {});
        eq("inherited object members are no fields", cleanFlexContext({"constructor": "x", "toString": "y"}, schema), {});
        """)


def test_currency(assert_js):
    """The scheduler requires all prices in one currency, so a new price follows those already set."""
    assert_js("""
        import { currencyInUnit, findFlexContextCurrency } from "/js/flex-context-utils.js";
        eq("a price unit names its currency", currencyInUnit("EUR/MWh"), "EUR");
        eq("so does a quantity", currencyInUnit("12.5 KRW/kW"), "KRW");
        eq("a power unit does not", currencyInUnit("100 kW"), null);
        eq("nor does nothing", currencyInUnit(undefined), null);

        eq("a fixed price anywhere decides",
           findFlexContextCurrency({"site-power-capacity": "1 MW", commodities: [{"consumption-price": "30 USD/MWh"}]}).currency,
           "USD");
        eq("sensor prices are collected for the caller to look up",
           findFlexContextCurrency({"consumption-price": {sensor: 4}, "production-price": {sensor: 5}, "aggregate-power": {sensor: 6}}),
           {currency: null, priceSensorIds: [4, 5]});
        eq("an empty flex-context names nothing", findFlexContextCurrency({}), {currency: null, priceSensorIds: []});
        """)


def test_commitment_values(assert_js):
    assert_js("""
        import { parseCommitmentValue, describeCommitmentValue } from "/js/flex-context-utils.js";
        eq("a sensor is referred to by id", parseCommitmentValue("sensor 536"), {sensor: 536});
        eq("in any casing and spacing", parseCommitmentValue("  Sensor   7 "), {sensor: 7});
        eq("anything else is a quantity", parseCommitmentValue(" 10 kW "), "10 kW");
        eq("including text that merely mentions a sensor", parseCommitmentValue("sensor 5 kW"), "sensor 5 kW");

        eq("a sensor reference reads back", describeCommitmentValue({sensor: 536}), "sensor 536");
        eq("a quantity reads back", describeCommitmentValue("10 kW"), "10 kW");
        eq("a number reads back", describeCommitmentValue(0), "0");
        eq("an unset value reads as nothing", [undefined, null, ""].map(describeCommitmentValue), [null, null, null]);
        for (const text of ["sensor 12", "0 EUR/MWh"]) {
            eq(`"${text}" survives a round trip`, describeCommitmentValue(parseCommitmentValue(text)), text);
        }
        """)
