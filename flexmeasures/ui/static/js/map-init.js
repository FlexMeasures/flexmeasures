
// Useful functions for our asset-specific Leaflet code

function addTileLayer(leafletMap, mapboxAccessToken) {
    var tileLayer = new L.tileLayer('https://api.mapbox.com/styles/v1/{id}/tiles/{z}/{x}/{y}?access_token={accessToken}', {
        attribution: 'Map data &copy; <a href="http://openstreetmap.org">OpenStreetMap</a> contributors, ' +
            '<a href="http://creativecommons.org/licenses/by-sa/2.0/">CC-BY-SA</a>, ' +
            'Imagery &copy <a href="http://mapbox.com">Mapbox</a>',
        tileSize: 512,
        maxZoom: 18,
        zoomOffset: -1,
        id: 'mapbox/streets-v11',
        accessToken: mapboxAccessToken
    });
    tileLayer.addTo(leafletMap);
}


function clickPan(e, data) {
    // set view such that the target asset lies slightly below the center of the map
    targetLatLng = e.target.getLatLng()
    targetZoom = assetMap.getZoom()
    targetPoint = assetMap.project(targetLatLng, targetZoom).subtract([0, 50]),
    targetLatLng = assetMap.unproject(targetPoint, targetZoom);
    assetMap.setView(targetLatLng, targetZoom);
}
