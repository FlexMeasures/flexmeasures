$(document).ready(function () {
    const btn = document.getElementById("delete-asset-button");
    if (!btn) return;
    const assetId = btn.dataset.assetId;

    $("#delete-asset-button").click(function () {
        if (confirm("Are you sure you want to delete this asset and all time series data associated with it?")) {
            window.location.href = "/assets/delete_with_data/" + assetId;
        }
    });
});

