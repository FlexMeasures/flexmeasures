var mymap = L.map('mapid').setView([33.3649, 126.6504], 10);

L.tileLayer('https://api.tiles.mapbox.com/v4/{id}/{z}/{x}/{y}.png?access_token=pk.eyJ1IjoibWFwYm94IiwiYSI6ImNpejY4NXVycTA2emYycXBndHRqcmZ3N3gifQ.rJcFIG214AriISLbB6B5aw', {
    maxZoom: 18,
    attribution: 'Map data &copy; <a href="http://openstreetmap.org">OpenStreetMap</a> contributors, ' +
        '<a href="http://creativecommons.org/licenses/by-sa/2.0/">CC-BY-SA</a>, ' +
        'Imagery © <a href="http://mapbox.com">Mapbox</a>',
    id: 'mapbox.streets'
}).addTo(mymap);

var LeafIcon = L.Icon.extend({
    options: {
        iconSize:     [21, 27], // size of the icon
        iconAnchor:   [10, 27], // point of the icon which will correspond to marker's location
        popupAnchor:  [0, -27] // point from which the popup should open relative to the iconAnchor
    }
});

var windIcon = new LeafIcon({iconUrl: 'public/icons/wind.png'});
var houseIcon = new LeafIcon({iconUrl: 'public/icons/house.png'});
var batIcon = new LeafIcon({iconUrl: 'public/icons/battery.svg'});

L.marker([33.4649, 126.3504], {icon: windIcon}).bindPopup('<a href="analytics">SD-Onshore</a>').addTo(mymap).openPopup();
L.marker([33.4649, 126.7504], {icon: windIcon}).bindPopup('<a href="analytics">HD-Onshore</a>').addTo(mymap);
L.marker([33.3649, 126.7504], {icon: windIcon}).bindPopup('<a href="analytics">SS-Onshore</a>').addTo(mymap);
L.marker([33.2649, 126.5504], {icon: houseIcon}).bindPopup('<a href="analytics">My BEMS</a>').addTo(mymap);
L.marker([33.3649, 126.5504], {icon: batIcon}).bindPopup('<a href="analytics">My BAT</a>').addTo(mymap);


var popup = L.popup();

function onMapClick(e) {
    popup
        .setLatLng(e.latlng)
        .setContent("You clicked the map at " + e.latlng.toString())
        .openOn(mymap);
}

// mymap.on('click', onMapClick);
