/**
 * UI Components
 * =============
 *
 * This file contains reusable UI components for the FlexMeasures frontend.
 * Moving forward, new UI elements and sub-components (graphs, cards, lists)
 * should be defined here to promote reusability and cleaner template files.
 */

import { getAsset, getAccount, getSensor, apiBasePath } from "./ui-utils.js";

/**
 * Helper function to add key-value information to a container.
 *
 * @param {string} label - The label text (e.g., "ID").
 * @param {string|number} value - The value to display.
 * @param {HTMLElement} infoDiv - The container element to append to.
 * @param {Object} resource - The generic resource object (Asset or Sensor).
 * @param {boolean} [isLink=false] - If true, renders the value as a hyperlink to the resource page.
 */
const addInfo = (label, value, infoDiv, resource, isLink = false) => {
  const b = document.createElement("b");
  b.textContent = `${label}: `;
  infoDiv.appendChild(b);
  const isSensor = resource.hasOwnProperty("unit");

  if (isLink) {
    const a = document.createElement("a");
    a.href = `${apiBasePath}/${isSensor ? "sensors" : "assets"}/${resource.id}`;
    a.textContent = value;
    infoDiv.appendChild(a);
  } else {
    infoDiv.appendChild(document.createTextNode(value));
  }
};

/**
 * Renders a card representing an Asset Plot configuration.
 *
 * Creates a visual element displaying the Asset ID, Name, and its associated
 * Flex Context or Flex Model configuration. Includes a remove button.
 *
 * @param {Object} assetPlot - The configuration object for the asset plot.
 *                             Expected structure: { asset: <id>, "flex-context"?: <string>, "flex-model"?: <string> }
 * @param {number} graphIndex - The index of the parent graph in the sensors_to_show array.
 * @param {number} plotIndex - The index of this specific plot within the graph's plots array.
 * @returns {Promise<HTMLElement>} The constructed HTML element representing the card.
 */
export async function renderAssetPlotCard(assetPlot, graphIndex, plotIndex) {
  const Asset = await getAsset(assetPlot.asset);
  let IsFlexContext = false;
  let IsFlexModel = false;
  let flexConfigValue = null;

  if ("flex-context" in assetPlot) {
    IsFlexContext = true;
    flexConfigValue = assetPlot["flex-context"];
  }

  if ("flex-model" in assetPlot) {
    IsFlexModel = true;
    flexConfigValue = assetPlot["flex-model"];
  }

  const container = document.createElement("div");
  container.className = "p-1 mb-3 border-bottom border-secondary";

  const flexDiv = document.createElement("div");
  flexDiv.className = "d-flex justify-content-between";

  const infoDiv = document.createElement("div");

  addInfo("ID", Asset.id, infoDiv, Asset, true);
  infoDiv.appendChild(document.createTextNode(", "));
  addInfo("Name", Asset.name, infoDiv, Asset);
  infoDiv.appendChild(document.createTextNode(", "));
  if (IsFlexContext) {
    addInfo("Flex Context", flexConfigValue, infoDiv, Asset);
  } else if (IsFlexModel) {
    addInfo("Flex Model", flexConfigValue, infoDiv, Asset);
  }

  const closeIcon = document.createElement("i");
  closeIcon.className = "fa fa-times";
  closeIcon.style.cursor = "pointer";
  closeIcon.setAttribute("data-bs-toggle", "tooltip");
  closeIcon.title = "Remove Asset Plot";

  // Attach the actual function here
  closeIcon.addEventListener("click", (e) => {
    e.stopPropagation(); // Prevent card selection click
    // removeAssetPlotFromGraph(graphIndex, plotIndex); // Note: Function reference needs to be available in scope
  });

  flexDiv.appendChild(infoDiv);
  flexDiv.appendChild(closeIcon);
  container.appendChild(flexDiv);

  return container;
}

/**
 * Renders a card representing a single Sensor.
 *
 * Creates a visual element displaying Sensor ID, Unit, Name, Asset Name,
 * and Account Name. Used within the list of sensors for a graph.
 *
 * @param {number} sensorId - The ID of the sensor to display.
 * @param {number} graphIndex - The index of the parent graph in the sensors_to_show array.
 * @param {number} sensorIndex - The index of this sensor within the graph's sensor list.
 * @returns {Promise<{element: HTMLElement, unit: string}>} An object containing the card element and the sensor's unit.
 */
export async function renderSensorCard(sensorId, graphIndex, sensorIndex) {
  const Sensor = await getSensor(sensorId);
  const Asset = await getAsset(Sensor.generic_asset_id);
  const Account = await getAccount(Asset.account_id);

  const container = document.createElement("div");
  container.className = "p-1 mb-3 border-bottom border-secondary";

  const flexDiv = document.createElement("div");
  flexDiv.className = "d-flex justify-content-between";

  const infoDiv = document.createElement("div");

  addInfo("ID", Sensor.id, infoDiv, Sensor, true);
  infoDiv.appendChild(document.createTextNode(", "));
  addInfo("Unit", Sensor.unit, infoDiv, Sensor);
  infoDiv.appendChild(document.createTextNode(", "));
  addInfo("Name", Sensor.name, infoDiv, Sensor);

  const spacer = document.createElement("div");
  spacer.style.paddingTop = "1px";
  infoDiv.appendChild(spacer);

  addInfo("Asset", Asset.name, infoDiv, Asset);
  infoDiv.appendChild(document.createTextNode(", "));
  addInfo("Account", Account?.name ? Account.name : "PUBLIC", infoDiv, Account);

  const closeIcon = document.createElement("i");
  closeIcon.className = "fa fa-times";
  closeIcon.style.cursor = "pointer";
  closeIcon.setAttribute("data-bs-toggle", "tooltip");
  closeIcon.title = "Remove Sensor";

  // Attach the actual function here
  closeIcon.addEventListener("click", (e) => {
    e.stopPropagation(); // Prevent card selection click
    removeSensorFromGraph(graphIndex, sensorIndex);
  });

  flexDiv.appendChild(infoDiv);
  flexDiv.appendChild(closeIcon);
  container.appendChild(flexDiv);

  // Return both the element and the unit (so we can check for mixed units later)
  return { element: container, unit: Sensor.unit };
}

/**
 * Renders a list of sensors for a specific graph card.
 *
 * Iterates through a list of sensor IDs, creates cards for them, and
 * aggregates their units to help detect unit mismatches.
 *
 * @param {number[]} sensorIds - Array of sensor IDs to render.
 * @param {number} graphIndex - The index of the parent graph being rendered.
 * @returns {Promise<{element: HTMLElement, uniqueUnits: string[]}>} An object containing the container element with all sensors and a list of unique units found.
 */
export async function renderSensorsList(sensorIds, graphIndex) {
  const listContainer = document.createElement("div");
  const units = [];

  if (sensorIds.length === 0) {
    listContainer.innerHTML = `<div class="alert alert-warning">No sensors added to this graph.</div>`;
    return { element: listContainer, uniqueUnits: [] };
  }

  // Using Promise.all to maintain order and wait for all sensors
  const results = await Promise.all(
    sensorIds.map((id, sIdx) => renderSensorCard(id, graphIndex, sIdx)),
  );

  results.forEach((res) => {
    listContainer.appendChild(res.element);
    units.push(res.unit);
  });

  return { element: listContainer, uniqueUnits: [...new Set(units)] }
};