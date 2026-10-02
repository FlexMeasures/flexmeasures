// Utils for the asset status page

/**
 * Fetch the status of every given sensor and collect the statuses they report.
 *
 * Each sensor is asked separately, and every request is waited for, including the ones that fail.
 * A sensor whose status cannot be fetched contributes no statuses,
 * but it never cuts the collection short, so the sensors that did answer are all reported.
 *
 * @param {Array} sensorIds - IDs of the sensors to fetch the status of.
 * @param {Function} fetchStatus - Called with a single sensor ID, returns a promise of that sensor's status response.
 * @param {Function} [onError] - Called with the sensor ID and the error, whenever a sensor's status could not be fetched.
 * @returns {Promise<Array>} A promise of the statuses of all sensors that answered, in the order the sensors were given.
 */
export function fetchSensorStatuses(sensorIds, fetchStatus, onError) {
    const reportError = onError || (() => {});
    return Promise.all(
        sensorIds.map((sensorId) =>
            // The call itself is wrapped, so that a fetcher which throws rather than rejects is handled here, too.
            Promise.resolve()
                .then(() => fetchStatus(sensorId))
                .then((response) => (response && response.sensors_data) || [])
                .catch((error) => {
                    reportError(sensorId, error);
                    return [];
                })
        )
    ).then((statusesPerSensor) => statusesPerSensor.flat());
}
