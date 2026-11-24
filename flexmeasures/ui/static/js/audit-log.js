/**
 * The audit-log tables on the asset and user pages.
 *
 * Event texts name assets, users and accounts, and plugins write their own,
 * so they are whatever a user or a plugin typed.
 * DataTables inserts cell data as HTML, so these columns are rendered as text.
 */

/**
 * One row of an audit-log table.
 *
 * @param {object} element - An entry from the audit-log API.
 * @returns {object} - The row, with the event time as HTML and the other cells as plain text.
 */
export function auditLogRow(element) {
  const naturalDateTime = new Date(element["event_datetime"]);
  const naturalDate = naturalDateTime.toLocaleDateString(undefined, { day: "2-digit", month: "short" });
  return {
    // Built from a parsed date only, so it holds no text from the API response.
    event_datetime: `<span title="${naturalDateTime}">${naturalDate}</span>`,
    event: element["event"],
    acting_user_name: `${element["active_user_name"]} (Id: ${element["active_user_id"]})`,
  };
}

/**
 * The columns of an audit-log table.
 *
 * @param {object} DataTable - The DataTables library.
 * @returns {object[]} - DataTables column definitions.
 */
export function auditLogColumns(DataTable = window.DataTable) {
  const asText = DataTable.render.text();
  return [
    { data: "event_datetime", title: "Event Datetime", orderable: true },
    { data: "event", title: "Event Name", orderable: false, width: "80%", render: asText },
    { data: "acting_user_name", title: "Acting User", orderable: false, render: asText },
  ];
}

/**
 * Turn a table into a server-side audit log.
 *
 * @param {string} selector - The table to turn into an audit log.
 * @param {string} apiPath - The audit-log endpoint, e.g. /api/v3_0/assets/1/auditlog.
 * @param {function} onError - Called with the failed request.
 * @returns {object} - The DataTables API instance.
 */
export function initAuditLogTable(selector, apiPath, onError = (request) => console.log("Error: ", request.statusText)) {
  return $(selector).DataTable({
    order: [[0, "desc"]],
    serverSide: true,
    columns: auditLogColumns(),
    ajax: function (data, callback, settings) {
      const filter = data["search"]["value"];
      const orderColumnIndex = data["order"][0]["column"];
      const orderDirection = data["order"][0]["dir"];
      const orderColumnName = data["columns"][orderColumnIndex]["data"];
      let url = `${window.location.origin}${apiPath}?page=${Math.floor(data["start"] / data["length"]) + 1}&per_page=${data["length"]}`;
      if (filter.length > 0) {
        url = `${url}&filter=${encodeURIComponent(filter)}`;
      }
      if (orderColumnName) {
        url = `${url}&sort_by=${orderColumnName}&sort_dir=${orderDirection}`;
      }
      $.ajax({
        type: "get",
        url: url,
        success: function (response, text) {
          callback({
            data: response["data"].map(auditLogRow),
            recordsTotal: response["num-records"],
            recordsFiltered: response["filtered-records"],
          });
        },
        error: function (request, status, error) {
          onError(request);
        },
      });
    },
  });
}
