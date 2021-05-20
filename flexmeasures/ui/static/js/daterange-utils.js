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