
// Create useful things for our asset-specific Leaflet code

var tileLayer = new L.tileLayer('https://api.tiles.mapbox.com/v4/{id}/{z}/{x}/{y}.png?access_token=pk.eyJ1IjoibWFwYm94IiwiYSI6ImNpejY4NXVycTA2emYycXBndHRqcmZ3N3gifQ.rJcFIG214AriISLbB6B5aw', {
    maxZoom: 18,
    attribution: 'Map data &copy; <a href="http://openstreetmap.org">OpenStreetMap</a> contributors, ' +
        '<a href="http://creativecommons.org/licenses/by-sa/2.0/">CC-BY-SA</a>, ' +
        'Imagery &copy <a href="http://mapbox.com">Mapbox</a>',
    id: 'mapbox.streets'
});

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
var carIcon = new LeafIcon({iconUrl: 'public/icons/car.svg'});
var sunIcon = new LeafIcon({iconUrl: 'public/icons/sun.svg'});


function custom_overlay_fade(p1, p2, p3) {
    image_overlay_fade = '<div class="my_container"><img src="' + p1 +
                         '" alt="' + p2 +
                         '" class="image"><div class="middle"><div class="text">' + p3 +
                         '</div></div></div>';
    return image_overlay_fade
}
