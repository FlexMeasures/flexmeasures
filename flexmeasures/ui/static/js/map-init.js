
// Useful functions for our asset-specific Leaflet code

function addTileLayer(leafletMap, mapboxAccessToken) {
    /*
    Add the tile layer for FlexMeasures.
    Configure tile size, Mapbox API access and attribution.
    */
    var tileLayer = new L.tileLayer('https://api.mapbox.com/styles/v1/{id}/tiles/{z}/{x}/{y}?access_token={accessToken}', {
        attribution: '© <a href="https://www.mapbox.com/about/maps/">Mapbox</a> © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> <strong><a href="https://www.mapbox.com/map-feedback/" target="_blank">Improve this map</a></strong>',
        tileSize: 512,
        maxZoom: 18,
        zoomOffset: -1,
        id: 'mapbox/streets-v11',
        accessToken: mapboxAccessToken
    });
    tileLayer.addTo(leafletMap);
    // add link for Mapbox logo (logo added via CSS)
    $("#" + leafletMap._container.id).append(
        '<a href="https://mapbox.com/about/maps" class="mapbox-logo" target="_blank">Mapbox</a>'
    );
}


function clickPan(e, data) {
    // set view such that the target asset lies slightly below the center of the map
    targetLatLng = e.target.getLatLng()
    targetZoom = assetMap.getZoom()
    targetPoint = assetMap.project(targetLatLng, targetZoom).subtract([0, 50]),
    targetLatLng = assetMap.unproject(targetPoint, targetZoom);
    assetMap.setView(targetLatLng, targetZoom);
}