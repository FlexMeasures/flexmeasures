
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


function clickZoom(e) {
    assetMap.setView(e.target.getLatLng());
}
