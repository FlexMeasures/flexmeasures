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
