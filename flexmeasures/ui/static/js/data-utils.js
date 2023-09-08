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

