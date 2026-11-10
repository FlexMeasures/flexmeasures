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


def test_flex_config_sensor_ids(assert_js):
    """The dialogues look up every sensor a config refers to, wherever the reference sits."""
    assert_js("""
        import { flexConfigSensorIds } from "/js/flex-context-utils.js";
        eq("a field holding a sensor is found", flexConfigSensorIds({"consumption-price": {sensor: 4}}), [4]);
        eq("so are the entries of a sensor list",
           flexConfigSensorIds({"inflexible-consumption": [{sensor: 1}, {sensor: 2, source: 3}]}),
           [1, 2]);
        eq("and the bare ids of the deprecated field",
           flexConfigSensorIds({"inflexible-device-sensors": [8, 9]}),
           [8, 9]);
        eq("and the bare ids a commitment is scoped to",
           flexConfigSensorIds({commodities: [{commitments: [{name: "peak", sensors: [11, 22]}]}]}),
           [11, 22]);
        eq("a reference inside a commitment is found too",
           flexConfigSensorIds({commodities: [{commitments: [{"up-price": {sensor: 5}}]}]}),
           [5]);
        eq("each sensor is named once", flexConfigSensorIds({a: {sensor: 4}, b: {sensor: 4}}), [4]);
        eq("numbers that are not sensor ids are left alone",
           flexConfigSensorIds({"site-power-capacity": 1000, source: 3, "relax-constraints": false}),
           []);
        eq("a config without references names nothing", flexConfigSensorIds({}), []);
        eq("and neither does an unset one", flexConfigSensorIds(null), []);
        """)


def test_unset_sensor_references(assert_js):
    """Deleting a sensor leaves its references without a sensor, which the editors have to find, wherever they sit."""
    assert_js("""
        import { isUnsetSensorReference, unsetSensorReferencePaths } from "/js/flex-context-utils.js";
        eq("a reference whose sensor was deleted", isUnsetSensorReference({sensor: null, default: "10 EUR/MWh"}), true);
        eq("is not one with a sensor, a fixed value or nothing",
           [{sensor: 4}, "10 EUR/MWh", null, [], {}].map(isUnsetSensorReference),
           [false, false, false, false, false]);
        eq("a top-level field is named by its name",
           unsetSensorReferencePaths({"production-price": {sensor: null, default: "1 EUR/MWh"}, "site-power-capacity": "1 MW"}),
           ["production-price"]);
        eq("a nested one by its path, counting list positions from 1",
           unsetSensorReferencePaths({commodities: [{commodity: "gas"}, {commodity: "heat", "consumption-price": {sensor: null, upper: "5 EUR/MWh"}}]}),
           ["commodities > 2 > consumption-price"]);
        eq("a config with all its sensors names nothing", unsetSensorReferencePaths({"production-price": {sensor: 4}}), []);
        eq("and neither does an unset one", unsetSensorReferencePaths(null), []);
        """)


def test_picking_a_sensor_keeps_what_a_deleted_sensor_left(assert_js):
    """The default, bounds and source filters a deleted sensor's reference kept are what the user meant to keep for its replacement."""
    assert_js("""
        import { referenceWithSensor } from "/js/flex-context-utils.js";
        eq("a field whose sensor was deleted keeps the rest of its reference",
           referenceWithSensor({sensor: null, default: "1 kWh", upper: "5 kWh", "source-types": ["forecaster"]}, 7),
           {sensor: 7, default: "1 kWh", upper: "5 kWh", "source-types": ["forecaster"]});
        eq("a field with a sensor starts afresh", referenceWithSensor({sensor: 3, default: "1 kWh"}, 7), {sensor: 7});
        eq("and so does a fixed value, or nothing", [referenceWithSensor("1 kWh", 7), referenceWithSensor(null, 7)],
           [{sensor: 7}, {sensor: 7}]);
        """)


def test_unset_sensor_reference_note(assert_js):
    """A field whose sensor was deleted says what scheduling does with it until a new sensor is picked."""
    assert_js("""
        import { unsetSensorReferenceNote } from "/js/flex-context-utils.js";
        eq("its default is used as a fixed value",
           unsetSensorReferenceNote({sensor: null, default: "10 EUR/MWh"}, "Site"),
           "The sensor of this field has been deleted. Pick a new sensor for it. Until then, its default (10 EUR/MWh) is used as a fixed value. Kept for the new sensor: default: 10 EUR/MWh.");
        eq("without a default, an ancestor's value applies",
           unsetSensorReferenceNote({sensor: null, "source-types": ["forecaster"]}, "Site"),
           'The sensor of this field has been deleted. Pick a new sensor for it. Until then, this field is ignored, so the value set on Site applies. Kept for the new sensor: source-types: ["forecaster"].');
        eq("or the field is ignored",
           unsetSensorReferenceNote({sensor: null}),
           "The sensor of this field has been deleted. Pick a new sensor for it. Until then, this field is ignored.");
        """)
