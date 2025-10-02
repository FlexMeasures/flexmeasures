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

export function processResourceRawJSON(schema, rawJSON) {
    let processedJSON = rawJSON.replace(/'/g, '"');
    // change None to null
    processedJSON = processedJSON.replace(/None/g, 'null');
    // change True to true and False to false
    processedJSON = processedJSON.replace('True', 'true');
    processedJSON = processedJSON.replace('False', 'false');
    // update the assetFlexModel fields
    processedJSON = JSON.parse(processedJSON);

    for (const [key, value] of Object.entries(processedJSON)) {
        if (key in schema) {
            schema[key] = processedJSON[key];
        } else {
            schema[key] = null;
        }
    }

    return processedJSON;
}

export function getFlexFieldTitle(fieldName) {
    return fieldName.split("-").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}

export function renderFlexFieldOptions(schema, options) {
    // comapare the assetFlexContext with the template and get the fields that are not set
    const assetFlexModel = Object.assign({}, schema, options);
    flexSelect.innerHTML = `<option value="blank">Select an option</option>`;
    for (const [key, value] of Object.entries(assetFlexModel)) {
        if (value === null || value.length === 0) {
            const option = document.createElement('option');
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
                <b>Sensor:</b> <a href="${apiBasePath}/sensors/${sensorData.id}">${sensorData.id}</a>,
                <b>Unit:</b> ${sensorData.unit},
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
        if (typeof newValue === 'function') {
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

export function renderSensorSearchResults(sensors, resultContainer, actionFunc) {
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
                            <b>ID:</b> <a href="${apiBasePath}/sensors/${sensor.id}">${sensor.id}</a>,
                            <b>Unit:</b> ${sensor.unit},
                            <b>Asset:</b> ${Asset.name},
                            <b>Account:</b> ${Account?.name ? Account.name : "PUBLIC"}
                        </p>
                    </div>
                </div>
            `;

        const cardBody = col.querySelector('.result-sensor-card');
        const addButton = document.createElement('button');
        addButton.className = 'btn btn-primary btn-sm'; // Removed me-2 mt-2 as it might be added by a parent div
        addButton.textContent = 'Add Sensor';

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
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = htmlString.trim();
    return tempDiv.firstChild;
}
