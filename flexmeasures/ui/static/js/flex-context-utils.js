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
