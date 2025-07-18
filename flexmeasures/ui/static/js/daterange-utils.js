// Date range utils
export function subtract(oldDate, nDays) {
    var newDate = new Date(oldDate)
    newDate.setDate(newDate.getDate() - nDays);
    return newDate;
}
export function thisMonth(oldDate) {
    var d1 = new Date(oldDate)
    d1.setDate(1);
    var d2 = new Date(d1.getFullYear(), d1.getMonth() + 1, 0);
    return [d1, d2];
};
export function lastNMonths(oldDate, nMonths) {
    var d0 = new Date(oldDate)
    var d1 = new Date(d0.getFullYear(), d0.getMonth() - nMonths + 2, 0);
    d1.setDate(1);
    var d2 = new Date(d0.getFullYear(), d0.getMonth() + 1, 0);
    return [d1, d2];
};
export function getOffsetBetweenTimezonesForDate(date, timezone1, timezone2) {
    const o1 = getTimeZoneOffset(date, timezone1)
    const o2 = getTimeZoneOffset(date, timezone2)
    return o2 - o1
}

function getTimeZoneOffset(date, timeZone) {

    // Abuse the Intl API to get a local ISO 8601 string for a given time zone.
    let iso = date.toLocaleString('en-CA', { timeZone, hour12: false }).replace(', ', 'T');

    // Include the milliseconds from the original timestamp
    iso += '.' + date.getMilliseconds().toString().padStart(3, '0');

    // Lie to the Date object constructor that it's a UTC time.
    const lie = new Date(iso + 'Z');

    // Return the difference in timestamps, as minutes
    // Positive values are West of GMT, opposite of ISO 8601
    // this matches the output of `Date.getTimeZoneOffset`
    return -(lie - date) / 60 / 1000;
}

/**
 * Count the number of Daylight Saving Time (DST) transitions within a given datetime range.
 * @param {Date} startDate - The start date of the datetime range.
 * @param {Date} endDate - The end date of the datetime range.
 * @param {number} increment - The number of days to increment between iterations.
 * @returns {number} The count of DST transitions within the specified range.
 */
export function countDSTTransitions(startDate, endDate, increment) {
    let transitions = 0;
    let currentDate = new Date(startDate);
    let nextDate = new Date(startDate);

    while (currentDate <= endDate) {
        const currentOffset = currentDate.getTimezoneOffset();
        nextDate.setDate(currentDate.getDate() + increment);
        if (nextDate > endDate) {
            nextDate = endDate;
        }
        const nextOffset = nextDate.getTimezoneOffset();

        if (currentOffset !== nextOffset) {
            transitions++;
        }
        currentDate.setDate(currentDate.getDate() + increment);
    }

    return transitions;
}

/**
 * Compute suggested date range shortcuts for navigating or adjusting a simulation time window.
 *
 * The function analyzes the given start and end dates along with the minimum resolution ("hour" or "day"),
 * and returns a set of meaningful, context-aware ranges such as "⇐ day", "⇐ week", "Whole week", etc.
 *
 * Behavior:
 * - When `minRes` is "hour":
 *   - If at least one week is selected: allows navigation by ±1 day and ±1 week, and shrinking to one day.
 *   - If less than one week is selected: allows navigation by ±1 day, and growing to the full current week (Mon–Sun).
 *
 * - When `minRes` is "day":
 *   - If ≥2 weeks selected: adds navigation by ±1 week and ±1 month, and shrinking to the first full week in range.
 *   - If 1 week selected: allows navigation by ±1 week and growing to the full current month.
 *   - If less than 1 week: allows navigation by ±1 day and growing to the full current week.
 *
 * Notes:
 * - Week boundaries are calculated based on Monday as the first day of the week.
 * - Month boundaries are calculated based on the calendar month of `startDate`.
 * - All returned date ranges are arrays of two Date objects: [startDate, endDate].
 *
 * @param {Date} startDate - Start of the current selection.
 * @param {Date} endDate - End of the current selection.
 * @param {string} minRes - Minimum resolution of the data, either "hour" or "day". Default is "hour".
 * @returns {Object} An object mapping human-readable labels to corresponding [startDate, endDate] ranges.
 */
export function computeSimulationRanges(startDate, endDate, minRes = "hour") {
    if (!startDate) {
      startDate = new Date();
    }
    if (!endDate) {
      endDate = new Date();
    }

    function addDays(date, days) {
        const result = new Date(date);
        result.setDate(result.getDate() + days);
        return result;
    }
    function addWeeks(date, weeks) {
        return addDays(date, weeks * 7);
    }
    function oneWeekSelected(d1, d2) {
        return +addDays(d1, 6) <= +d2;
    }
    function twoWeeksSelected(d1, d2) {
        return +addDays(d1, 13) <= +d2;
    }
    function findFirstMonday(date) {
        const result = new Date(date);
        const day = result.getDay(); // 0 = Sunday, 1 = Monday, ..., 6 = Saturday
        const offset = (8 - day) % 7; // days until next Monday
        result.setDate(result.getDate() + offset);
        return result;
    }

    const dayOfWeek = (startDate.getDay() + 6) % 7; // 0 = Monday
    const startOfThisWeek = addDays(startDate, -dayOfWeek);
    const thisWeek = [startOfThisWeek, addDays(startOfThisWeek, 6)];
    if (minRes === "hour") {
        if (oneWeekSelected(startDate, endDate)) {
            return {
                "⇐ week": [addDays(startDate, -7), addDays(endDate, -7)],
                "⇐ day": [addDays(startDate, -1), addDays(endDate, -1)],
                "One day": [startDate, startDate],  // shrink to the first day in range
                "day ⇒": [addDays(startDate, 1), addDays(endDate, 1)],
                "week ⇒": [addDays(startDate, 7), addDays(endDate, 7)]
            };
        } else {  // less than one week selected
            return {
                "⇐ day": [addDays(startDate, -1), addDays(endDate, -1)],
                "Whole week": thisWeek,  // grow to the full week (based on the start date)
                "day ⇒": [addDays(startDate, 1), addDays(endDate, 1)]
            };
        }
    } else if (minRes === "day") {
        const year = startDate.getFullYear();
        const month = startDate.getMonth(); // 0-based

        function getMonthRange(y, m) {
            const start = new Date(y, m, 1);
            const end = new Date(y, m + 1, 1); // first day of next month
            return [start, addDays(end, -1)];
        }

        const lastMonth = getMonthRange(year, month - 1);
        const thisMonth = getMonthRange(year, month);
        const nextMonth = getMonthRange(year, month + 1);
        if (twoWeeksSelected(startDate, endDate)) {
            const firstMonday = findFirstMonday(startDate);
            return {
                "⇐ month": lastMonth,
                "⇐ week": [addDays(startDate, -7), addDays(endDate, -7)],
                "One week": [firstMonday, addDays(firstMonday, 6)],  // shrink to the first full week in range
                "week ⇒": [addDays(startDate, 7), addDays(endDate, 7)],
                "month ⇒": nextMonth
            };
        } else if (oneWeekSelected(startDate, endDate)) {
            return {
                "⇐ week": [addDays(startDate, -7), addDays(endDate, -7)],
                "Whole month": thisMonth,  // grow to the full month (based on the start date)
                "week ⇒": [addDays(startDate, 7), addDays(endDate, 7)]
            };
        } else {  // less than one week selected
            return {
                "⇐ day": [addDays(startDate, -1), addDays(endDate, -1)],
                "Whole week": thisWeek,  // grow to the full week (based on the start date)
                "day ⇒": [addDays(startDate, 1), addDays(endDate, 1)]
            };
        }
    } else {
        throw new Error(`Unsupported minimum resolution: ${minRes}`);
    }
}

/**
 * Encode the query string of a relative URL to ensure proper URL encoding of special characters.
 *
 * This function preserves the base path and re-encodes the query string using URLSearchParams.
 * It ensures that characters like `+` (often mistakenly interpreted as spaces in form submissions)
 * are correctly encoded as `%2B`, along with other special characters like `:` and `&`.
 *
 * For example:
 *   Input:  "path?date=2025-06-16T00:00:00+02:00"
 *   Output: "path?date=2025-06-16T00%3A00%3A00%2B02%3A00"
 *
 * @param {string} rawUrl - A relative URL (e.g., "path?foo=bar&date=...").
 * @returns {string} The same URL with the query string safely encoded.
 */
export function encodeUrlQuery(rawUrl) {
    const [path, query] = rawUrl.split("?");
    if (!query) return rawUrl;  // No query to encode

    const params = new URLSearchParams(query);
    return `${path}?${params.toString()}`;
}
