$(document).ready(function () {
    const btn = document.getElementById("copy-asset-button");
    if (!btn) return;
    const assetId = btn.dataset.assetId;

    $("#copy-asset-button").click(function () {
        if (confirm("Are you sure you want to copy this asset and all its children?")) {
            fetch("/api/v3_0/assets/" + assetId + "/copy", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin"
            })
            .then(response => {
                if (response.ok) return response.json();
                const contentType = response.headers.get("content-type");
                if (contentType && contentType.includes("application/json")) {
                    return response.json().then(err => {
                        throw new Error(err.message || response.statusText || "Copy failed");
                    });
                }
                throw new Error(response.statusText || "Copy failed");
            })
            .then(data => {
                showToast("Asset copied successfully.", "success");
                setTimeout(() => {
                    window.location.href = "/assets/" + data.asset + "/properties";
                }, 1500);
            })
            .catch(err => {
                showToast("Failed to copy asset: " + err.message, "error");
            });
        }
    });
});

