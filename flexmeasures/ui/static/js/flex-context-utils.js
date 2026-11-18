/**
 * Helpers for the flex-context editor on the asset context page (assets/asset_context.html).
 *
 * These hold the editor's decisions that do not need the page:
 * which fields take which kinds of values, what is sent on saving,
 * and how commitment values are read from and written to text.
 * The page keeps the DOM and the state; the schema is passed in rather than read from the page,
 * so each decision can be tested on its own.
 */

// Pulls the currency code out of a price unit, e.g. "EUR" from "EUR/MWh" or "12 KRW/kW".
const PRICE_UNIT_PATTERN = /([A-Z]{3})\/[kMG]?W/;

/**
 * Whether a field only takes sensors, and so offers no "Fixed value" tab in the editor.
 *
 * @param {Object} schemaSpecs - The UI flex-context schema, by field name.
 * @param {string} fieldName - The field to ask about.
 * @returns {boolean}
 */
export function isSensorOnlyField(schemaSpecs, fieldName) {
  // typeTwo = a single sensor reference, typeFour = a list of sensors.
  const backendType = schemaSpecs[fieldName]?.["types"]?.["backend"];
  return backendType === "typeTwo" || backendType === "typeFour";
}

/**
 * Whether a field holds a list of sensors.
 *
 * Such fields (e.g. inflexible-consumption and inflexible-production) keep their card active,
 * so several sensors can be added in a row.
 *
 * @param {Object} schemaSpecs - The UI flex-context schema, by field name.
 * @param {string} fieldName - The field to ask about.
 * @returns {boolean}
 */
export function isSensorListField(schemaSpecs, fieldName) {
  return schemaSpecs[fieldName]?.["types"]?.["backend"] === "typeFour";
}

/**
 * The sensor id of one entry of a sensor list field.
 *
 * Entries are sensor references ({"sensor": <id>}, possibly with source filters);
 * the deprecated inflexible-device-sensors field holds bare ids.
 *
 * @param {Object|number} entry - A sensor reference, or a bare sensor id.
 * @returns {number} - The sensor id.
 */
export function entrySensorId(entry) {
  return typeof entry === "object" && entry !== null ? entry["sensor"] : entry;
}

// The flex-config keys whose value is a bare sensor id, rather than a {"sensor": <id>} reference.
const SENSOR_ID_KEYS = ["sensor", "inflexible-device-sensors", "sensors"];

/**
 * Every sensor a flex-config refers to, wherever in it the reference sits.
 *
 * A reference is {"sensor": <id>}, which can sit at any depth: in a field, in a list entry, or inside a commitment.
 * Two fields hold bare ids instead: the deprecated inflexible-device-sensors field,
 * and the sensors a commitment is scoped to.
 * The ids are what a dialogue has to look up, and a reference can outlive its sensor,
 * so the lookups are also how a dangling reference is found.
 *
 * @param {Object|null} flexConfig - A flex-context or flex-model.
 * @returns {number[]} - The referenced sensor ids, each one once.
 */
export function flexConfigSensorIds(flexConfig) {
  const sensorIds = new Set();

  function collect(value, key) {
    if (Array.isArray(value)) {
      value.forEach((entry) => collect(entry, key));
    } else if (value !== null && typeof value === "object") {
      for (const [childKey, childValue] of Object.entries(value)) {
        collect(childValue, childKey);
      }
    } else if (Number.isInteger(value) && SENSOR_ID_KEYS.includes(key)) {
      sensorIds.add(value);
    }
  }

  collect(flexConfig, null);

  return [...sensorIds];
}

/**
 * Whether a value is a sensor reference whose sensor was unset, which is what deleting a sensor leaves behind.
 *
 * Deleting a sensor keeps the rest of each reference to it, such as its default, bounds and source filters,
 * so that they are still in place when a new sensor is picked for the field.
 * The API refuses such a reference, so it has to get a sensor again before the configuration can be saved.
 *
 * @param {*} value - A flex-config value.
 * @returns {boolean}
 */
export function isUnsetSensorReference(value) {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    "sensor" in value &&
    value["sensor"] === null
  );
}

/**
 * Where a flex-config holds references whose sensor was deleted.
 *
 * Such a reference can sit at any depth, such as in a commodity's flex-context or inside a commitment,
 * so each one is named by its path, e.g. "commodities > 1 > consumption-price", counting list positions from 1.
 *
 * @param {Object|null} flexConfig - A flex-context or flex-model.
 * @returns {string[]} - The path of each such reference.
 */
export function unsetSensorReferencePaths(flexConfig) {
  const paths = [];

  function walk(value, path) {
    if (isUnsetSensorReference(value)) {
      paths.push(path.join(" > "));
    } else if (Array.isArray(value)) {
      value.forEach((entry, index) => walk(entry, [...path, String(index + 1)]));
    } else if (value !== null && typeof value === "object") {
      for (const [key, childValue] of Object.entries(value)) {
        walk(childValue, [...path, key]);
      }
    }
  }

  walk(flexConfig, []);
  return paths;
}

/**
 * The reference a field gets when a sensor is picked for it.
 *
 * A field whose sensor was deleted keeps what its reference kept, such as its default, bounds and source filters,
 * as the user most likely means to replace the deleted sensor.
 * Any other field starts a fresh reference.
 *
 * @param {*} currentValue - The field's value before the sensor was picked.
 * @param {number} sensorId - The picked sensor.
 * @returns {Object} - The field's new sensor reference.
 */
export function referenceWithSensor(currentValue, sensorId) {
  return isUnsetSensorReference(currentValue)
    ? { ...currentValue, sensor: sensorId }
    : { sensor: sensorId };
}

/**
 * What the editors say on the card of a field whose sensor was deleted.
 *
 * Until a new sensor is picked, scheduling uses the reference's default as a fixed value,
 * or ignores the field if it has no default,
 * in which case a value an ancestor asset sets for the field applies instead.
 *
 * @param {Object} reference - The reference whose sensor was deleted.
 * @param {string|null} [inheritedFrom=null] - The name of the ancestor asset whose value applies instead, if any.
 * @returns {string} - The text to show, for the caller to escape if it builds markup from it.
 */
export function unsetSensorReferenceNote(reference, inheritedFrom = null) {
  let effect;
  if ("default" in reference) {
    effect = `Until then, its default (${reference["default"]}) is used as a fixed value.`;
  } else if (inheritedFrom !== null) {
    effect = `Until then, this field is ignored, so the value set on ${inheritedFrom} applies.`;
  } else {
    effect = "Until then, this field is ignored.";
  }
  const kept = Object.entries(reference)
    .filter(([key]) => key !== "sensor")
    .map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`);
  const keptNote = kept.length > 0 ? ` Kept for the new sensor: ${kept.join(", ")}.` : "";
  return `The sensor of this field has been deleted. Pick a new sensor for it. ${effect}${keptNote}`;
}

// Fields managed by the commodity tab bar rather than as cards.
const STRUCTURAL_FIELDS = ["commodities", "commodity"];

/**
 * Whether a field is managed by the commodity tab bar, rather than shown as a card.
 *
 * @param {string} fieldName - The field to ask about.
 * @returns {boolean}
 */
export function isStructuralField(fieldName) {
  return STRUCTURAL_FIELDS.includes(fieldName);
}

/**
 * Whether a field can be set in the commodity scope the editor is working on.
 *
 * The editor works either on the top-level flex-context (the electricity commodity),
 * or on one entry of its "commodities" list, which takes only the fields marked per-commodity.
 *
 * @param {Object} schemaSpecs - The UI flex-context schema, by field name.
 * @param {string} fieldName - The field to ask about.
 * @param {?number} activeCommodityIndex - Index into "commodities", or null for the top level.
 * @returns {boolean}
 */
export function isFieldAvailableInScope(schemaSpecs, fieldName, activeCommodityIndex) {
  if (isStructuralField(fieldName)) {
    return false;
  }
  if (activeCommodityIndex === null) {
    return true;
  }
  return schemaSpecs[fieldName]?.["per-commodity"] === true;
}

/**
 * The part of the flex-context that the editor is working on.
 *
 * @param {Object} flexContext - The whole flex-context of the asset.
 * @param {?number} activeCommodityIndex - Index into "commodities", or null for the top level.
 * @returns {Object} - The top-level flex-context, or one of its commodity contexts.
 */
export function getActiveContext(flexContext, activeCommodityIndex) {
  if (activeCommodityIndex === null) {
    return flexContext;
  }
  return flexContext["commodities"][activeCommodityIndex];
}

/**
 * Prepare a flex-context for saving, in place.
 *
 * Fields the schema does not know are taken out, sparing the structural ones
 * (the commodities list itself is not part of the UI schema),
 * and so are fields left empty.
 *
 * @param {Object} flexContext - The whole flex-context of the asset, which is modified.
 * @param {Object} schema - Default values by field name; its keys are the fields that may be saved.
 * @returns {Object} - The same flex-context, for convenience.
 */
export function cleanFlexContext(flexContext, schema) {
  function cleanContext(context, isCommodityContext) {
    for (const key in context) {
      if (isCommodityContext && key === "commodity") {
        continue;
      }
      if (!isCommodityContext && key === "commodities") {
        continue;
      }
      if (!Object.prototype.hasOwnProperty.call(schema, key)) {
        delete context[key];
      }
    }

    for (const [key, value] of Object.entries(context)) {
      if (value === null || value === "" || (Array.isArray(value) && value.length === 0)) {
        delete context[key];
      }
    }
  }

  cleanContext(flexContext, false);
  if (flexContext["commodities"]) {
    for (const commodityContext of flexContext["commodities"]) {
      cleanContext(commodityContext, true);
    }
  }
  return flexContext;
}

/**
 * The currency code in a price unit, if any.
 *
 * @param {string} text - A unit or a quantity, e.g. "EUR/MWh" or "12 EUR/MWh".
 * @returns {?string} - The currency code, e.g. "EUR", or null.
 */
export function currencyInUnit(text) {
  const currencyMatch = (text || "").match(PRICE_UNIT_PATTERN);
  return currencyMatch ? currencyMatch[1] : null;
}

/**
 * Look for the currency the flex-context already prices in.
 *
 * The scheduler requires all prices to share one currency,
 * so a new price should follow any price already set.
 * Fixed values say so directly;
 * for sensor references, the caller has to look up the sensor's unit.
 *
 * @param {Object} flexContext - The whole flex-context of the asset.
 * @returns {{currency: ?string, priceSensorIds: number[]}} -
 *     The currency of the first fixed price found (null if none),
 *     and the ids of sensors referenced by price fields, to fall back on.
 */
export function findFlexContextCurrency(flexContext) {
  const contexts = [flexContext, ...(flexContext["commodities"] || [])];
  const priceSensorIds = [];
  for (const context of contexts) {
    for (const [key, value] of Object.entries(context || {})) {
      if (typeof value === "string") {
        const currency = currencyInUnit(value);
        if (currency) {
          return { currency: currency, priceSensorIds: priceSensorIds };
        }
      }
      if (key.includes("price") && value !== null && typeof value === "object" && value["sensor"]) {
        priceSensorIds.push(value["sensor"]);
      }
    }
  }
  return { currency: null, priceSensorIds: priceSensorIds };
}

/**
 * Turn free text into a commitment value.
 *
 * "sensor 536" (any casing) becomes a sensor reference; anything else is kept as a fixed quantity string.
 *
 * @param {string} raw - The text as typed.
 * @returns {Object|string} - A sensor reference, or the trimmed text.
 */
export function parseCommitmentValue(raw) {
  const sensorMatch = raw.trim().toLowerCase().match(/^sensor\s+(\d+)$/);
  if (sensorMatch) {
    return { sensor: parseInt(sensorMatch[1], 10) };
  }
  return raw.trim();
}

/**
 * Describe a commitment value in plain text, the inverse of parseCommitmentValue.
 *
 * @param {*} value - A sensor reference or a fixed quantity string.
 * @returns {?string} - The description, or null when the value is not set.
 */
export function describeCommitmentValue(value) {
  if (value === undefined || value === null || value === "") {
    return null;
  }
  if (typeof value === "object" && value["sensor"]) {
    return `sensor ${value["sensor"]}`;
  }
  return String(value);
}
