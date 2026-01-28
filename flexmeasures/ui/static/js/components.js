import { getAsset, getAccount, getSensor, apiBasePath } from "./ui-utils.js";

const addInfo = (label, value, infoDiv, Resource, isLink = false) => {
  const b = document.createElement("b");
  b.textContent = `${label}: `;
  infoDiv.appendChild(b);
  const isSensor = Resource.hasOwnProperty("unit");

  if (isLink) {
    const a = document.createElement("a");
    a.href = `${apiBasePath}/${isSensor ? "sensors" : "assets"}/${Resource.id}`;
    a.textContent = value;
    infoDiv.appendChild(a);
  } else {
    infoDiv.appendChild(document.createTextNode(value));
  }
};

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
    // removeAssetPlotFromGraph(graphIndex, plotIndex);
  });

  flexDiv.appendChild(infoDiv);
  flexDiv.appendChild(closeIcon);
  container.appendChild(flexDiv);

  return container;
}

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

  return { element: listContainer, uniqueUnits: [...new Set(units)] };
}

/**
 * Renders the header for a graph card.
 * @param {string} title - The current title of the graph.
 * @param {number} index - The index of the graph in the list.
 * @param {boolean} isEditing - Whether this specific graph is in edit mode.
 * @param {Function} onSave - Function to call when "Save" is clicked or "Enter" is pressed.
 * @param {Function} onEdit - Function to call when "Edit" is clicked.
 */
export function renderGraphHeader(title, index, isEditing, onSave, onEdit) {
  const header = document.createElement("div");
  header.className = "d-flex align-items-center mb-2";

  if (isEditing) {
    // 1. Title Input
    const input = document.createElement("input");
    input.type = "text";
    input.className = "form-control me-2";
    input.id = `editTitle_${index}`;
    input.value = title;

    // Save on Enter key
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        onSave(index);
      }
    });

    // 2. Save Button
    const saveBtn = document.createElement("button");
    saveBtn.className = "btn btn-success btn-sm";
    saveBtn.textContent = "Save";
    saveBtn.onclick = (e) => {
      e.stopPropagation(); // Prevent card selection
      onSave(index);
    };

    header.appendChild(input);
    header.appendChild(saveBtn);

    // Auto-focus the input
    setTimeout(() => input.focus(), 0);
  } else {
    // 1. Display Title
    const h5 = document.createElement("h5");
    h5.className = "card-title me-2 mb-0";
    h5.textContent = title;

    // 2. Edit Button
    const editBtn = document.createElement("button");
    editBtn.className = "btn btn-warning btn-sm";
    editBtn.textContent = "Edit";
    editBtn.onclick = (e) => {
      e.stopPropagation(); // Prevent card selection
      onEdit(index);
    };

    header.appendChild(h5);
    header.appendChild(editBtn);
  }

  return header;
}
