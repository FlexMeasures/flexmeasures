// Data source utils

/**
 * Extracts unique values of a specified nested property from an array of JSON objects.
 *
 * @param {Array} data - An array of JSON objects from which to extract unique values.
 * @param {string} key - The dot-separated key representing the nested property (e.g., 'source.id').
 * @returns {Array} An array containing the unique values of the specified nested property.
 *
 * @example
 * const data = [
 *   {"id": 1, "name": "foo", "source": {"id": 4, "name": "bar"}},
 *   {"id": 2, "name": "baz", "source": {"id": 4, "name": "qux"}},
 *   {"id": 3, "name": "quux", "source": {"id": 5, "name": "corge"}}
 * ];
 *
 * const key = 'source.id';
 * const uniqueSourceIds = getUniqueValues(data, key);
 * console.log(uniqueSourceIds); // Output: [4, 5]
 */
export function getUniqueValues(data, key) {
    var lookup = {};
    var items = data;
    var results = [];

    for (var item, i = 0; item = items[i++];) {
        var val = getValueByNestedKey(item, key);

        if (!(val in lookup)) {
            lookup[val] = 1;
            results.push(val);
        }
    }
    return results;
}

/**
 * Retrieves the value of a nested property in an object using a dot-separated key.
 *
 * @param {Object} obj - The input JavaScript object from which to retrieve the nested value.
 * @param {string} key - The dot-separated key representing the nested property (e.g., 'source.id').
 * @returns {*} The value of the nested property if found, otherwise, returns undefined.
 *
 * @example
 * const jsonString = '{"id":11,"name":"ajax","subject":"OR","mark":63,"source":{"id":4,"name":"foo"}}';
 * const jsonObject = JSON.parse(jsonString);
 *
 * const key = 'source.id';
 * const sourceId = getValueByNestedKey(jsonObject, key);
 * console.log(sourceId); // Output: 4
 */
function getValueByNestedKey(obj, key) {
    const keys = key.split('.');
    let value = obj;
    for (const k of keys) {
        if (value[k] === undefined) {
            return undefined; // Property not found
        }
        value = value[k];
    }
    return value;
}

// From https://stackoverflow.com/a/49332027/13775459
function toISOLocal(d) {
    var z  = n =>  ('0' + n).slice(-2);
    var zz = n => ('00' + n).slice(-3);
    var off = d.getTimezoneOffset();
    var sign = off > 0? '-' : '+';
    off = Math.abs(off);

    return d.getFullYear() + '-' +
    z(d.getMonth()+1) + '-' +
    z(d.getDate()) + 'T' +
    z(d.getHours()) + ':'  +
    z(d.getMinutes()) + ':' +
    z(d.getSeconds()) + '.' +
    zz(d.getMilliseconds()) +
    sign + z(off/60|0) + ':' + z(off%60);
}

// Create a function to convert data to CSV
export function convertToCSV(data) {
    if (data.length === 0) {
        return "";
    }

    // Extract column names from the first object in the data array
    const columns = Object.keys(data[0]);

    // Create the header row
    const headerRow = columns.join(',') + '\n';

    // Create the data rows
    const dataRows = data.map(row => {
        const rowData = columns.map(col => {
            const value = row[col];
            if (typeof value === 'object' && value !== null) {
                return value.description || '';
            } else if (col === 'event_start' || col === 'belief_time') {
                // Check if the column is a timestamp column
                const timestamp = parseInt(value);
                if (!isNaN(timestamp)) {
                    const date = new Date(timestamp); // Convert to Date
                    // Format the date in ISO8601 format and localize to the specified timezone
                    // return date.toISOString();  // Use this instead of toISOLocal to get UTC instead
                    return toISOLocal(date);
                }
            } else if (col === 'belief_horizon') {
                // Check if the column is 'belief_horizon' (duration in ms)
                const durationMs = parseInt(value);
                if (!isNaN(durationMs)) {
                    // Check if the duration is zero
                    if (durationMs === 0) {
                        return 'PT0H';
                    }

                    // Check if the duration is negative
                    const isNegative = durationMs < 0;

                    // Calculate absolute duration in seconds
                    const absDurationSeconds = Math.abs(durationMs) / 1000;

                    // Calculate hours, minutes, and seconds
                    const hours = Math.floor(absDurationSeconds / 3600);
                    const minutes = Math.floor((absDurationSeconds % 3600) / 60);
                    const seconds = Math.floor(absDurationSeconds % 60);

                    // Format the duration as ISO8601 duration
                    let iso8601Duration = isNegative ? '-PT' : 'PT';
                    if (hours > 0) {
                        iso8601Duration += hours + 'H';
                    }
                    if (minutes > 0) {
                        iso8601Duration += minutes + 'M';
                    }
                    if (seconds > 0) {
                        iso8601Duration += seconds + 'S';
                    }

                    return iso8601Duration;
                }
            }
            return value;
        });
        return rowData.join(',');
    });

    // Combine the header row and data rows
    return "data:text/csv;charset=utf-8," + headerRow + dataRows.join('\n');
}