export const apiBasePath = window.location.origin;

// Fetch Account Details
export async function getAccount(accountId) {
  const cacheKey = `account_${accountId}`;
  const cachedData = localStorage.getItem(cacheKey);

  if (cachedData) {
    return JSON.parse(cachedData);
  }

  const apiUrl = apiBasePath + "/api/v3_0/accounts/" + accountId;
  const response = await fetch(apiUrl);
  const account = await response.json();

  localStorage.setItem(cacheKey, JSON.stringify(account));

  return account;
}

// Fetch Asset Details
export async function getAsset(assetId, useCache = true) {
  const cacheKey = `asset_${assetId}`;
  const cachedData = localStorage.getItem(cacheKey);

  if (cachedData && useCache) {
    return JSON.parse(cachedData);
  }

  const apiUrl = apiBasePath + "/api/v3_0/assets/" + assetId;
  const response = await fetch(apiUrl);
  const asset = await response.json();

  localStorage.setItem(cacheKey, JSON.stringify(asset));

  return asset;
}

// Fetch Sensor Details
export async function getSensor(id) {
  const cacheKey = `sensor_${id}`;
  const cachedData = localStorage.getItem(cacheKey);

  if (cachedData) {
    return JSON.parse(cachedData);
  }

  const apiUrl = apiBasePath + "/api/v3_0/sensors/" + id;
  const response = await fetch(apiUrl);
  const sensor = await response.json();

  localStorage.setItem(cacheKey, JSON.stringify(sensor));

  return sensor;
}

export function processResourceRawJSON(schema, rawJSON, allowExtra = false) {
  /*
    allowExtra - whether to allow extra fields in the rawJSON that are not in the schema. 
    If false, those fields will be ignored.
  */
  let processedJSON = rawJSON.replace(/'/g, '"');
  // change None to null, True to true and False to false
  processedJSON = processedJSON.replaceAll("None", "null");
  processedJSON = processedJSON.replaceAll("True", "true");
  processedJSON = processedJSON.replaceAll("False", "false");
  // update the assetFlexModel fields
  processedJSON = JSON.parse(processedJSON);
  const extraFields = {};

  for (const [key, value] of Object.entries(processedJSON)) {
    if (key in schema) {
      schema[key] = processedJSON[key];
    } else {
      if (!allowExtra) {
        schema[key] = null;
      } else {
        schema[key] = processedJSON[key];
        extraFields[key] = processedJSON[key];
      }
    }
  }

  return [processedJSON, extraFields];
}

export function getFlexFieldTitle(fieldName) {
  return fieldName;
  // .split("-")
  // .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
  // .join(" ");
}

export function renderFlexFieldOptions(schema, options) {
  // compare the assetFlexContext with the template and get the fields that are not set
  const assetFlexModel = Object.assign({}, schema, options);
  flexSelect.innerHTML = `<option value="blank">Select an option</option>`;
  for (const [key, value] of Object.entries(assetFlexModel)) {
    if (value === null || value.length === 0) {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = getFlexFieldTitle(key);
      flexSelect.appendChild(option);
    }
  }
}

export async function renderSensor(sensorId) {
  if (!sensorId) {
    return `<div class="text-info">No sensor data available</div>`;
  }

  const sensorData = await getSensor(sensorId);
  const Asset = await getAsset(sensorData.generic_asset_id);
  const Account = await getAccount(Asset.account_id);

  return `
        <div class="d-flex justify-content-between">
            <div>
                <b>Sensor:</b> <a href="${apiBasePath}/sensors/${
                  sensorData.id
                }">${sensorData.id}</a>,
                <b>Unit:</b> ${
                  sensorData.unit === ""
                    ? '<span title="A sensor recording numbers rather than physical or economical quantities.">dimensionless</span>'
                    : sensorData.unit
                },
                <b>Name:</b> ${sensorData.name},
                <div style="padding-top: 1px;"></div>
                <b>Asset:</b> ${Asset.name},
                <b>Account:</b> ${Account?.name ? Account.name : "PUBLIC"}
            </div>
        </div>
    `;
}

/**
 * A custom function to mimic React's useState for simple DOM manipulation.
 *
 * @param {*} initialValue - The initial value for the state.
 * @param {function(value: *): void} renderFunction - A callback function that
 * will be executed whenever the state updates. This function should contain
 * the logic to update the relevant DOM elements. It receives the new state value.
 * @returns {[function(): *, function(*): void]} - A tuple/array containing:
 * - A getter function for the current state value (to be reactive, we need a function).
 * - A setter function to update the state value, which also triggers the renderFunction.
 */
export function createReactiveState(initialValue, renderFunction) {
  let value = initialValue;

  // The function that returns the current state value
  function getValue() {
    return value;
  }

  // The function that updates the state value
  function setValue(newValue) {
    if (typeof newValue === "function") {
      value = newValue(value);
    } else {
      value = newValue;
    }
    if (renderFunction) {
      renderFunction(value);
    }
  }

  if (renderFunction) {
    renderFunction(value);
  }

  return [getValue, setValue];
}

export function renderSensorSearchResults(
  sensors,
  resultContainer,
  actionFunc,
) {
  if (!resultContainer) {
    console.error("Result container is not defined.");
    showToast("Error", "Result container is not defined.", "error");
    return;
  }

  if (actionFunc && typeof actionFunc !== "function") {
    console.error("Action function is not a valid function.");
    showToast("Error", "Action function is not a valid function.", "error");
    return;
  }

  resultContainer.innerHTML = "";
  if (sensors.length === 0) {
    resultContainer.innerHTML = "<h4>No sensors found</h4>";
    return;
  }

  sensors.forEach(async (sensor) => {
    const Asset = await getAsset(sensor.generic_asset_id);
    const Account = await getAccount(Asset.account_id);

    const col = document.createElement("div");
    col.classList.add("col-12", "mb-1");

    col.innerHTML = `
                <div class="card m-0">
                    <div class="card-body p-0 result-sensor-card">
                        <h5 class="card-title">${sensor.name}</h5>
                        <p class="card-text">
                            <b>ID:</b> <a href="${apiBasePath}/sensors/${
                              sensor.id
                            }">${sensor.id}</a>,
                            <b>Unit:</b> ${
                              sensor.unit === ""
                                ? '<span title="A sensor recording numbers rather than physical or economical quantities.">dimensionless</span>'
                                : sensor.unit
                            },
                            <b>Asset:</b> ${Asset.name},
                            <b>Account:</b> ${
                              Account?.name ? Account.name : "PUBLIC"
                            }
                        </p>
                    </div>
                </div>
            `;

    const cardBody = col.querySelector(".result-sensor-card");
    const addButton = document.createElement("button");
    addButton.className = "btn btn-primary btn-sm"; // Removed me-2 mt-2 as it might be added by a parent div
    addButton.textContent = "Use Sensor";

    addButton.onclick = () => {
      if (actionFunc) {
        actionFunc(sensor.id);
      } else {
        console.error("Action function is not defined.");
        showToast("Error", "Action function is not defined.", "error");
      }
    };
    cardBody.appendChild(addButton);

    resultContainer.appendChild(col);
  });
}

export function convertHtmlToElement(htmlString) {
  const tempDiv = document.createElement("div");
  tempDiv.innerHTML = htmlString.trim();
  return tempDiv.firstChild;
}

// Set default asset view
export function setDefaultAssetView(checkbox, view_name) {
  // Get the checked status of the checkbox
  const isChecked = checkbox.checked;

  const apiBasePath = window.location.origin;
  fetch(apiBasePath + "/api/v3_0/assets/default_asset_view", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": "{{ csrf_token }}",
    },
    body: JSON.stringify({
      default_asset_view: view_name,
      use_as_default: isChecked,
    }),
  })
    .then((response) => response.json())
    .catch((error) => {
      console.error("Error during API call:", error);
    });
}

export function setDefaultLegendPosition(checkbox) {
  // Get the checked status of the checkbox
  const isChecked = checkbox.checked;

  const apiBasePath = window.location.origin;
  fetch(apiBasePath + "/api/v3_0/assets/keep_legends_below_graphs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": "{{ csrf_token }}",
    },
    body: JSON.stringify({
      keep_legends_below_graphs: isChecked,
    }),
  })
    .then((response) => {
      response.json();
      location.reload();
    })
    .catch((error) => {
      console.error("Error during API call:", error);
    });
}

/**
 * Swaps an item in an array with its neighbor based on direction.
 * @param {Array} array - The source array.
 * @param {number} index - The index of the item to move.
 * @param {'up' | 'down'} direction - The direction to move.
 * @returns {Array} A new array with the items swapped.
 */
export function moveArrayItem(array, index, direction) {
  // Create a shallow copy to avoid mutating the original array
  const newArray = [...array];

  const isUp = direction === "up";
  const targetIndex = isUp ? index - 1 : index + 1;

  // Boundary Checks:
  // Don't move 'up' if at the start, or 'down' if at the end.
  if (targetIndex < 0 || targetIndex >= newArray.length) {
    return newArray;
  }

  // Perform the swap using destructuring
  [newArray[index], newArray[targetIndex]] = [
    newArray[targetIndex],
    newArray[index],
  ];

  return newArray;
}

/**
 * Optionally show a confirmation dialog, then perform a fetch request.
 *
 * Error responses are normalised: a JSON body's `message` field is used
 * when available, otherwise the HTTP status text is used. Network errors
 * bubble up unchanged. The raw Response is passed to onSuccess so each
 * caller can decide how to consume it (e.g. parse JSON or read response.url).
 *
 * @param {string|null} confirmMessage - Text shown in the confirm dialog, or
 *                                       null/undefined to skip confirmation.
 * @param {string}   url            - URL to fetch.
 * @param {object}   options        - fetch() options (method, headers, …).
 * @param {function} onSuccess      - Called with the Response on success.
 * @param {string}   errorPrefix    - Prefix for the showToast error message.
 */
function confirmAndFetch(confirmMessage, url, options, onSuccess, errorPrefix) {
    if (confirmMessage && !confirm(confirmMessage)) return;
    fetch(url, options)
        .then(response => {
            if (response.ok) return response;
            const contentType = response.headers.get("content-type");
            if (contentType && contentType.includes("application/json")) {
                return response.json().then(err => {
                    throw new Error(err.message || response.statusText || "Request failed");
                });
            }
            throw new Error(response.statusText || "Request failed");
        })
        .then(onSuccess)
        .catch(err => showToast(errorPrefix + ": " + err.message, "error"));
}

/**
 * Attach click handlers to all elements with the "js-copy-asset-btn" class.
 * Each button must carry a data-asset-id attribute.
 * An optional data-target-account-id attribute causes the copy to land in that
 * account instead of creating a sibling under the same parent/account.
 * Ctrl/Cmd-click opens the resulting asset page in a new tab.
 *
 * Note: plain account members can create copies indefinitely (GenericAsset
 * create-children is open to all account members) but cannot delete the
 * resulting assets (deletion requires account-admin). Account admins are
 * responsible for pruning unwanted copies.
 */
export function initCopyAssetButtons() {
    document.querySelectorAll(".js-copy-asset-btn").forEach(btn => {
        const assetId = btn.dataset.assetId;
        // Present on the "copy to my account" button; absent on the sibling-copy button.
        const targetAccountId = btn.dataset.targetAccountId || null;

        btn.addEventListener("click", function (event) {
            const url = targetAccountId
                ? "/api/v3_0/assets/" + assetId + "/copy?account=" + targetAccountId
                : "/api/v3_0/assets/" + assetId + "/copy";
            confirmAndFetch(
                null,
                url,
                {method: "POST", headers: {"Content-Type": "application/json"}, credentials: "same-origin"},
                response => response.json().then(data => {
                    showToast("Asset copied successfully.", "success");
                    setTimeout(() => {
                        const dest = "/assets/" + data.asset + "/properties";
                        window.open(dest, "_blank");
                    }, 1500);
                }),
                "Failed to copy asset"
            );
        });
    });
}

export function initDeleteAssetButton() {
    const btn = document.getElementById("delete-asset-button");
    if (!btn) return;
    const assetId = btn.dataset.assetId;

    btn.addEventListener("click", function () {
        confirmAndFetch(
            "Are you sure you want to delete this asset and all time series data associated with it?",
            "/assets/delete_with_data/" + assetId,
            {method: "GET", credentials: "same-origin"},
            response => {
                showToast("Asset deleted successfully.", "success");
                setTimeout(() => {
                    window.location.href = response.url;
                }, 1500);
            },
            "Failed to delete asset"
        );
    });
}
