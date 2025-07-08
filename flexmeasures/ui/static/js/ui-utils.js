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
            flexSelect.innerHTML += `<option value="${key}">${getFlexFieldTitle(key)}</option>`;
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
                <div class="mb-2">
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
