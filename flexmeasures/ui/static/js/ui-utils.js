export const apiBasePath = window.location.origin;

/**
 * Escape text for use in HTML, as element content or as a quoted attribute value.
 *
 * Names, units and descriptions are whatever a user typed,
 * so they must be escaped wherever they are built into markup rather than set as textContent.
 *
 * @param {*} value - The text to escape; null and undefined become the empty string.
 * @returns {string} - The escaped text.
 */
export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/**
 * Markup for a sensor unit, explaining the empty unit of a dimensionless sensor.
 *
 * @param {string} unit - The sensor's unit.
 * @returns {string} - HTML.
 */
export function unitHtml(unit) {
  return unit === ""
    ? '<span title="A sensor recording numbers rather than physical or economical quantities.">dimensionless</span>'
    : escapeHtml(unit);
}

/**
 * Look up one resource in the API, remembering it in localStorage.
 *
 * A configuration can still refer to a sensor or an asset which is gone,
 * for instance one deleted directly in the database, where our cleanup on deletion never ran.
 * A lookup the API does not answer with a resource therefore yields no resource, rather than raising,
 * and says whether that is because the resource is gone:
 * only a 404 means it is, while a server error or a network failure only means we could not tell just now.
 * A resource which is gone is forgotten, so that a copy remembered earlier does not stand in for it.
 *
 * @param {string} path - The resource's path within the API.
 * @param {string} cacheKey - Where to remember the resource in localStorage.
 * @param {boolean} [useCache=true] - Whether a remembered resource may be handed out.
 * @returns {Promise<{resource: Object|null, gone: boolean}>} - The resource (or null), and whether the API says it does not exist.
 */
async function lookUpResource(path, cacheKey, useCache = true) {
  const cachedData = useCache ? localStorage.getItem(cacheKey) : null;

  if (cachedData) {
    const cached = JSON.parse(cachedData);
    // Earlier versions remembered whatever the API answered,
    // which for a resource that is gone is an error payload rather than a resource.
    if (cached !== null && cached.id !== undefined) {
      return { resource: cached, gone: false };
    }
    localStorage.removeItem(cacheKey);
  }

  let response;
  try {
    response = await fetch(apiBasePath + path);
  } catch (error) {
    // A network failure says nothing about whether the resource is there.
    return { resource: null, gone: false };
  }
  if (response.status === 404) {
    localStorage.removeItem(cacheKey);
    return { resource: null, gone: true };
  }
  if (!response.ok) {
    return { resource: null, gone: false };
  }

  let resource;
  try {
    resource = await response.json();
  } catch (error) {
    return { resource: null, gone: false };
  }

  localStorage.setItem(cacheKey, JSON.stringify(resource));

  return { resource, gone: false };
}

// Fetch Account Details
export async function getAccount(accountId) {
  const { resource } = await lookUpResource(
    "/api/v3_0/accounts/" + accountId,
    `account_${accountId}`,
  );
  return resource;
}

/**
 * Look up an asset, saying whether one we could not hand out is gone.
 *
 * @param {number|string} assetId - The asset's id.
 * @param {boolean} [useCache=true] - Whether a remembered asset may be handed out.
 * @returns {Promise<{resource: Object|null, gone: boolean}>} - See lookUpResource.
 */
export async function lookUpAsset(assetId, useCache = true) {
  return lookUpResource(
    "/api/v3_0/assets/" + assetId,
    `asset_${assetId}`,
    useCache,
  );
}

// Fetch Asset Details
export async function getAsset(assetId, useCache = true) {
  return (await lookUpAsset(assetId, useCache)).resource;
}

/**
 * Look up a sensor, saying whether one we could not hand out is gone.
 *
 * @param {number|string} sensorId - The sensor's id.
 * @param {boolean} [useCache=true] - Whether a remembered sensor may be handed out.
 * @returns {Promise<{resource: Object|null, gone: boolean}>} - See lookUpResource.
 */
export async function lookUpSensor(sensorId, useCache = true) {
  return lookUpResource(
    "/api/v3_0/sensors/" + sensorId,
    `sensor_${sensorId}`,
    useCache,
  );
}

// Fetch Sensor Details
export async function getSensor(id, useCache = true) {
  return (await lookUpSensor(id, useCache)).resource;
}

/**
 * The account an asset belongs to, for an asset which may not be there.
 *
 * Every place that names a sensor also names the account its asset belongs to,
 * and an asset we could not look up, or a public asset, has no account to name.
 *
 * @param {Object|null} asset - The asset, or null if it could not be looked up.
 * @returns {Promise<Object|null>} - The account, or null if there is none to name.
 */
export async function getAccountOfAsset(asset) {
  if (asset === null || asset.account_id === null || asset.account_id === undefined) {
    return null;
  }
  return getAccount(asset.account_id);
}

/**
 * How many of the given sensors the API says are gone.
 *
 * A sensor which merely failed to load is not counted,
 * as it may well still be there.
 *
 * @param {Array<number>} sensorIds - The sensors to look up, each one once.
 * @returns {Promise<number>} - How many of them the API says do not exist.
 */
export async function countSensorsGone(sensorIds) {
  const lookups = await Promise.all(sensorIds.map((id) => lookUpSensor(id)));
  return lookups.filter((lookup) => lookup.gone).length;
}

/**
 * The warning a dialogue shows above its configuration when some of its references point at something gone.
 *
 * Each dangling reference is also named where it sits,
 * but that can be out of sight, such as on another commodity's tab,
 * so the dialogue as a whole says how many there are, in the same words in each dialogue.
 *
 * @param {number} count - How many references point at something gone.
 * @param {string} [thing="asset or sensor"] - What one reference points at.
 * @param {string} [things="assets or sensors"] - What several references point at.
 * @returns {HTMLElement|null} - The warning, or null if there is nothing to warn about.
 */
export function unavailableReferencesWarning(
  count,
  thing = "asset or sensor",
  things = "assets or sensors",
) {
  if (count === 0) {
    return null;
  }
  const warning = document.createElement("div");
  warning.className = "alert alert-warning mt-2";
  warning.setAttribute("role", "alert");
  warning.textContent =
    count === 1
      ? `1 saved reference is not available anymore, as the ${thing} it points at has been deleted. You can remove or update it.`
      : `${count} saved references are not available anymore, as the ${things} they point at have been deleted. You can remove or update them.`;
  return warning;
}

/**
 * The warning a flex-config dialogue shows above its configuration when some of its fields lost their sensor.
 *
 * Deleting a sensor leaves its references in place without a sensor, and the API refuses to save those,
 * so the user has to know before saving that each such field needs a new sensor.
 * Each field is also marked on its card, but that can be out of sight, such as on another commodity's tab.
 *
 * @param {number} count - How many fields lost their sensor.
 * @returns {HTMLElement|null} - The warning, or null if there is nothing to warn about.
 */
export function deletedSensorReferencesWarning(count) {
  if (count === 0) {
    return null;
  }
  const warning = document.createElement("div");
  warning.className = "alert alert-warning mt-2";
  warning.setAttribute("role", "alert");
  warning.textContent =
    count === 1
      ? "1 field refers to a sensor that has been deleted. Changes can only be saved once it has a new sensor or a fixed value, or is removed."
      : `${count} fields refer to a sensor that has been deleted. Changes can only be saved once each of them has a new sensor or a fixed value, or is removed.`;
  return warning;
}

/**
 * How both dialogues word a reference to a sensor we could not look up.
 *
 * Configurations hold sensor ids, and a sensor can be deleted without those references being cleaned up,
 * so the flex-config and graph dialogues have to name such a reference rather than fail on it.
 * Only a sensor the API says does not exist is called gone;
 * a lookup which failed for another reason, such as a server error, says no more than that.
 *
 * @param {number|string} sensorId - The id the configuration still refers to.
 * @param {boolean} gone - Whether the API says the sensor does not exist.
 * @returns {string} - The text to show, for the caller to escape if it builds markup from it.
 */
export function missingSensorLabel(sensorId, gone) {
  return gone
    ? `Sensor ${sensorId} is not available anymore (it may have been deleted).`
    : `Sensor ${sensorId} could not be loaded just now.`;
}

/**
 * Convert the Python representation of a dict (as Jinja renders one) to JSON.
 *
 * Only what `repr` writes for JSON-like data is handled:
 * strings in either quote style, with Python's escapes, and the constants None, True and False.
 * Those constants are only replaced outside strings, so a value such as "Nonetheless" survives.
 *
 * @param {string} text - The Python representation.
 * @returns {string} - The same data as JSON.
 */
export function pythonReprToJSON(text) {
  const constants = { None: "null", True: "true", False: "false" };
  const escapes = { n: "\n", t: "\t", r: "\r", b: "\b", f: "\f", 0: "\0" };
  let out = "";
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (ch === "'" || ch === '"') {
      let value = "";
      let j = i + 1;
      while (j < text.length && text[j] !== ch) {
        if (text[j] === "\\") {
          const next = text[j + 1];
          const hexLength = { x: 2, u: 4, U: 8 }[next];
          if (hexLength) {
            value += String.fromCodePoint(parseInt(text.slice(j + 2, j + 2 + hexLength), 16));
            j += 2 + hexLength;
          } else {
            value += next in escapes ? escapes[next] : next;
            j += 2;
          }
          continue;
        }
        value += text[j];
        j++;
      }
      out += JSON.stringify(value);
      i = j + 1;
      continue;
    }
    const word = /^[A-Za-z_]\w*/.exec(text.slice(i));
    if (word) {
      out += constants[word[0]] ?? word[0];
      i += word[0].length;
      continue;
    }
    out += ch;
    i++;
  }
  return out;
}

export function processResourceRawJSON(schema, rawJSON, allowExtra = false) {
  /*
    rawJSON - the resource's fields, either as an object or as the Python representation of a dict.
    allowExtra - whether to allow extra fields in the rawJSON that are not in the schema.
    If false, those fields will be ignored.
  */
  const processedJSON =
    typeof rawJSON === "string" ? JSON.parse(pythonReprToJSON(rawJSON)) : rawJSON;
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

  const { resource: sensorData, gone } = await lookUpSensor(sensorId);
  if (sensorData === null) {
    return `<div class="text-warning">${escapeHtml(missingSensorLabel(sensorId, gone))}</div>`;
  }
  const Asset = await getAsset(sensorData.generic_asset_id);
  const Account = await getAccountOfAsset(Asset);

  return `
        <div class="d-flex justify-content-between">
            <div>
                <b>Sensor:</b> <a href="${apiBasePath}/sensors/${
                  sensorData.id
                }">${sensorData.id}</a>,
                <b>Unit:</b> ${unitHtml(sensorData.unit)},
                <b>Name:</b> ${escapeHtml(sensorData.name)},
                <div style="padding-top: 1px;"></div>
                <b>Asset:</b> ${Asset === null ? "unknown" : escapeHtml(Asset.name)},
                <b>Account:</b> ${Account?.name ? escapeHtml(Account.name) : "PUBLIC"}
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
    const Account = await getAccountOfAsset(Asset);

    const col = document.createElement("div");
    col.classList.add("col-12", "mb-1");

    col.innerHTML = `
                <div class="card m-0">
                    <div class="card-body p-0 result-sensor-card">
                        <h5 class="card-title">${escapeHtml(sensor.name)}</h5>
                        <p class="card-text">
                            <b>ID:</b> <a href="${apiBasePath}/sensors/${
                              sensor.id
                            }">${sensor.id}</a>,
                            <b>Unit:</b> ${unitHtml(sensor.unit)},
                            <b>Asset:</b> ${Asset === null ? "unknown" : escapeHtml(Asset.name)},
                            <b>Account:</b> ${
                              Account?.name ? escapeHtml(Account.name) : "PUBLIC"
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

/**
 * Remember this asset view as the one to open per default, or stop doing so.
 *
 * The click has already moved the checkbox, so a refusal puts it back:
 * a box left ticked claims a preference the server never stored.
 *
 * @param {HTMLInputElement} checkbox - The checkbox the user just clicked.
 * @param {string} view_name - The name of the view currently shown.
 * @returns {Promise} Settles once the preference was stored or the failure was reported.
 */
export function setDefaultAssetView(checkbox, view_name) {
  // Get the checked status of the checkbox
  const isChecked = checkbox.checked;

  const apiBasePath = window.location.origin;
  return fetch(apiBasePath + "/api/ui/session/default-asset-view", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": "{{ csrf_token }}",
    },
    body: JSON.stringify({
      "default-asset-view": view_name,
      "use-as-default": isChecked,
    }),
  })
    .then(rejectIfNotOk)
    .catch((error) => {
      checkbox.checked = !isChecked;
      showToast("Could not save your default view: " + error.message, "error");
    });
}

/**
 * Remember whether graph legends belong below their graph, and reload to apply it.
 *
 * The reload happens only once the preference was stored,
 * since reloading after a refusal redraws the old setting and reads as the toggle bouncing back.
 *
 * @param {HTMLInputElement} checkbox - The checkbox the user just clicked.
 * @returns {Promise} Settles once the preference was stored or the failure was reported.
 */
export function setDefaultLegendPosition(checkbox) {
  // Get the checked status of the checkbox
  const isChecked = checkbox.checked;

  const apiBasePath = window.location.origin;
  return fetch(apiBasePath + "/api/ui/session/keep-legends-below-graphs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": "{{ csrf_token }}",
    },
    body: JSON.stringify({
      "keep-legends-below-graphs": isChecked,
    }),
  })
    .then(rejectIfNotOk)
    .then(() => {
      location.reload();
    })
    .catch((error) => {
      checkbox.checked = !isChecked;
      showToast(
        "Could not save your legend placement: " + error.message,
        "error",
      );
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
 * Recursively flattens nested error payloads into readable strings.
 * Handles objects, arrays, and primitive values, building dot-notation paths.
 * @param {any} payload - The error data to flatten (object, array, string, etc.)
 * @param {string|null} parentKey - The parent key for building dot-notation paths.
 * @returns {Array<string>} Array of flattened error strings.
 */
export function flattenErrorPayload(payload, parentKey = null) {
  if (payload === null || payload === undefined) return [];
  if (
    typeof payload === "string" ||
    typeof payload === "number" ||
    typeof payload === "boolean"
  ) {
    return [
      parentKey
        ? `\n <b>${parentKey}</b>: ${String(payload)}`
        : String(payload),
    ];
  }
  if (Array.isArray(payload)) {
    return payload.flatMap((item) => flattenErrorPayload(item, parentKey));
  }
  if (typeof payload === "object") {
    return Object.entries(payload).flatMap(([key, value]) => {
      const nextParentKey = parentKey ? `${parentKey}.${key}` : key;
      return flattenErrorPayload(value, nextParentKey);
    });
  }
  return [parentKey ? `${parentKey}: ${String(payload)}` : String(payload)];
}

/**
 * Safely extracts error messages from API error payloads.
 * Tries multiple candidates in order: message.json → message → error → full payload.
 * Returns a semicolon-joined readable string with fallback to status text.
 * @param {any} errorData - The error response data object.
 * @param {string} fallbackMessage - Message to return if no error found (e.g., response.statusText).
 * @returns {string} Readable error message.
 */
export function extractApiErrorMessage(errorData, fallbackMessage) {
  if (!errorData || typeof errorData !== "object")
    return fallbackMessage || "Unknown error";
  const candidates = [
    errorData?.message?.json,
    errorData?.message,
    errorData?.error,
    errorData,
  ];
  for (const candidate of candidates) {
    const lines = flattenErrorPayload(candidate)
      .map((line) => String(line).trim())
      .filter((line) => line.length > 0);
    if (lines.length > 0) return lines.join("; ");
  }
  return fallbackMessage || "Unknown error";
}

/**
 * Turn an error response into a rejection that carries the server's own message.
 *
 * `fetch` rejects only on a network-level failure, so a 4xx or 5xx arrives as a resolved response;
 * a caller that does not check `response.ok` reads a refusal as a success and drops it silently.
 * A JSON body is read through `extractApiErrorMessage`, so that a validation error reaches the user as the fields it named, rather than as the status text.
 *
 * @param {Response} response - The response to inspect.
 * @returns {Response} The same response, when it was a success.
 */
function rejectIfNotOk(response) {
  if (response.ok) return response;
  const fallback = response.statusText || "Request failed";
  const contentType = response.headers.get("content-type");
  if (contentType && contentType.includes("application/json")) {
    return response.json().then((err) => {
      throw new Error(extractApiErrorMessage(err, fallback));
    });
  }
  throw new Error(fallback);
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
    .then(rejectIfNotOk)
    .then(onSuccess)
    .catch((err) => showToast(errorPrefix + ": " + err.message, "error"));
}

/**
 * Report the automations that an asset copy left out, as returned by the copy endpoint.
 *
 * Copying an asset copies its automations too, but an automation that cannot be copied safely is skipped,
 * so say which ones those were and why, rather than let the user find out when a forecast never arrives.
 *
 * An automation's name is whatever a user typed, and `showToast` renders the message as HTML,
 * so the parts that come from the response are escaped here.
 *
 * @param {object} data - The copy endpoint's response body.
 * @returns {boolean} - Whether anything was reported, so the caller can leave the toast up long enough to read.
 */
export const SKIPPED_AUTOMATIONS_TOAST_DELAY = 8000;

export function reportSkippedAutomations(data) {
  const skipped = (data && data["skipped-automations"]) || [];
  if (skipped.length === 0) return false;
  const details = skipped
    .map(
      (automation) =>
        '"' +
        escapeHtml(automation.name) +
        '" — ' +
        escapeHtml(automation.reason),
    )
    .join(" ");
  showToast(
    skipped.length + " automation(s) could not be copied: " + details,
    "info",
    { delay: SKIPPED_AUTOMATIONS_TOAST_DELAY },
  );
  return true;
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
  document.querySelectorAll(".js-copy-asset-btn").forEach((btn) => {
    const assetId = btn.dataset.assetId;
    // Present on the "copy to my account" button; absent on the sibling-copy button.
    const targetAccountId = btn.dataset.targetAccountId || null;

    btn.addEventListener("click", function (event) {
      const openInNewTab = event.ctrlKey || event.metaKey;
      const url = targetAccountId
        ? "/api/v3_0/assets/" + assetId + "/copy?account=" + targetAccountId
        : "/api/v3_0/assets/" + assetId + "/copy";
      confirmAndFetch(
        null,
        url,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
        },
        (response) =>
          response.json().then((data) => {
            showToast("Asset copied successfully.", "success");
            const redirectDelay = reportSkippedAutomations(data) ? SKIPPED_AUTOMATIONS_TOAST_DELAY : 1500;
            setTimeout(() => {
              const dest = "/assets/" + data.asset + "/properties";
              if (openInNewTab) {
                window.open(dest, "_blank");
              } else {
                window.location.href = dest;
              }
            }, redirectDelay);
          }),
        "Failed to copy asset",
      );
    });
  });
}

export function initDeleteAssetButton() {
  const btn = document.getElementById("delete-asset-button");
  if (!btn) return;
  const assetId = btn.dataset.assetId;
  const parentAssetId = btn.dataset.parentAssetId;

  btn.addEventListener("click", function () {
    confirmAndFetch(
      "Are you sure you want to delete this asset and all time series data associated with it?",
      apiBasePath + "/api/v3_0/assets/" + assetId,
      { method: "DELETE", credentials: "same-origin" },
      () => {
        showToast("Asset deleted successfully.", "success");
        setTimeout(() => {
          window.location.href = parentAssetId
            ? "/assets/" + parentAssetId + "/context"
            : "/assets";
        }, 1500);
      },
      "Failed to delete asset",
    );
  });
}

/**
 * Attach click handlers to all elements with the "js-reset-password-btn" class.
 * Each button must carry a data-user-id attribute,
 * and data-own-password="true" when it resets the password of the logged-in user,
 * whose session the reset ends.
 */
export function initResetPasswordButtons() {
  document.querySelectorAll(".js-reset-password-btn").forEach((btn) => {
    const ownPassword = btn.dataset.ownPassword === "true";
    btn.addEventListener("click", function () {
      confirmAndFetch(
        ownPassword
          ? "Reset your password? You will be logged out, and receive an email with instructions to choose a new one."
          : "Reset this user's password? They will be logged out, their API access token will stop working, and they will receive an email with instructions to choose a new one.",
        apiBasePath + "/api/v3_0/users/" + btn.dataset.userId + "/password-reset",
        { method: "PATCH", credentials: "same-origin" },
        () => {
          if (ownPassword) {
            window.location.href = "/";
            return;
          }
          showToast(
            "The password has been reset, and instructions to choose a new one have been sent.",
            "success",
          );
        },
        "Failed to reset the password",
      );
    });
  });
}

/**
 * Poll a background job until it reaches a terminal state (finished or failed).
 *
 * Calls GET /api/v3_0/jobs/<uuid> every `intervalMs` milliseconds and updates
 * a toast notification as the status changes.  Polling stops automatically on
 * success, failure, or network error, and also when the optional AbortSignal
 * fires (useful for component/page teardown).
 *
 * @param {string}      jobUuid     - UUID returned by the upload endpoint.
 * @param {object}      [options]
 * @param {number}      [options.intervalMs=3000]      - Polling interval in ms.
 * @param {string}      [options.processingMessage="Processing…"] - Toast text while queued/started.
 * @param {string}      [options.successMessage="Job completed successfully."] - Toast text on finish.
 * @param {string}      [options.errorMessage]         - Override toast text on failure (defaults to the
 *                                                       server message when absent).
 * @param {AbortSignal} [options.signal]               - Abort polling externally (e.g. page unload).
 * @param {function}    [options.onStatus]             - Called with the full response JSON on each poll.
 * @param {function}    [options.onFinished]           - Called with the full response JSON on finish.
 * @param {function}    [options.onFailed]             - Called with the full response JSON on failure.
 * @returns {function} stopPolling - Call to cancel polling manually.
 */
export function pollJobStatus(jobUuid, options = {}) {
    const {
        intervalMs = 3000,
        processingMessage = "Processing\u2026",
        successMessage = "Job completed successfully.",
        errorMessage = null,
        signal = null,
        onStatus = null,
        onFinished = null,
        onFailed = null,
    } = options;

    const url = `${apiBasePath}/api/v3_0/jobs/${encodeURIComponent(jobUuid)}`;

    // Show an initial "processing" info toast right away.
    showToast(processingMessage, "info");

    let stopped = false;

    function stop() {
        stopped = true;
        clearInterval(intervalId);
    }

    // Honour an external AbortSignal (e.g. page navigation / component unmount).
    if (signal) {
        signal.addEventListener("abort", stop, { once: true });
    }

    // Polls are not sent while one is still waiting for its answer,
    // or a slow endpoint would answer several of them with the same final status, each reported again.
    let inFlight = false;

    async function poll() {
        if (stopped || inFlight) return;
        inFlight = true;
        try {
            await pollOnce();
        } finally {
            inFlight = false;
        }
    }

    async function pollOnce() {
        let data;
        try {
            const response = await fetch(url, { credentials: "same-origin" });
            try {
                data = await response.json();
            } catch {
                data = null;
            }
            // A failed job is answered with 422 and its status in the body, so that is the one error response to read as the job's status.
            // Other error responses carry a status too (ERROR for a job that is gone, UNAUTHORIZED after logging out), but not a job's.
            if (!response.ok && !(response.status === 422 && data && data.status)) {
                const reason = data && data.message ? ` (${data.message})` : "";
                throw new Error(`HTTP ${response.status}: ${response.statusText}${reason}`);
            }
        } catch (err) {
            stop();
            showToast("Could not reach job status endpoint: " + err.message, "error");
            if (onFailed) onFailed(null);
            return;
        }

        const status = (data.status || "").toUpperCase();
        if (onStatus) onStatus(data);

        if (status === "FINISHED") {
            stop();
            showToast(successMessage, "success");
            if (onFinished) onFinished(data);
        } else if (status === "FAILED" || status === "STOPPED" || status === "CANCELED") {
            stop();
            const msg = errorMessage || data.message || "Job failed.";
            showToast(msg, "error");
            if (onFailed) onFailed(data);
        } else if (status === "STARTED") { // This is the shown status when ingestion is in progress
              // show a inprogress message
              const inProgressMessage = data.message || "Job is in progress.";
              showToast(inProgressMessage, "info");
        } else {
            // QUEUED / STARTED / DEFERRED / SCHEDULED → keep polling, show status updates
            const statusToast = data.message || `Job status: ${status}`;
            console.log(`[pollJobStatus] Still processing: ${statusToast}`);
        }
    }

    // Poll immediately on first tick, then on each interval.
    const intervalId = setInterval(poll, intervalMs);
    poll();

    return stop;
}
