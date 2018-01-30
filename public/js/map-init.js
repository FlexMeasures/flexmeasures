var mymap = L.map('mapid').setView([33.3649, 126.6504], 10);

L.tileLayer('https://api.tiles.mapbox.com/v4/{id}/{z}/{x}/{y}.png?access_token=pk.eyJ1IjoibWFwYm94IiwiYSI6ImNpejY4NXVycTA2emYycXBndHRqcmZ3N3gifQ.rJcFIG214AriISLbB6B5aw', {
    maxZoom: 18,
    attribution: 'Map data &copy; <a href="http://openstreetmap.org">OpenStreetMap</a> contributors, ' +
        '<a href="http://creativecommons.org/licenses/by-sa/2.0/">CC-BY-SA</a>, ' +
        'Imagery � <a href="http://mapbox.com">Mapbox</a>',
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

L.marker([33.4649, 126.3504], {icon: windIcon}).bindPopup('<a href="analytics">SD-Onshore</a>' +
                                                          custom_overlay_fade('/public/live-mock-imgs/0.6.png',
                                                                      'Load',
                                                                      'Currently producing at 26 MW (60% capacity)'))
                                                          .addTo(mymap).openPopup();
L.marker([33.4649, 126.7504], {icon: windIcon}).bindPopup('<a href="analytics">HW-Onshore</a>' +
                                                          custom_overlay_fade('/public/live-mock-imgs/0.7.png',
                                                                      'Load',
                                                                      'Currently producing at 7.8 MW (70% capacity)'))
                                                          .addTo(mymap);
L.marker([33.3649, 126.7504], {icon: windIcon}).bindPopup('<a href="analytics">SS-Onshore</a>' +
                                                          custom_overlay_fade('/public/live-mock-imgs/0.9.png',
                                                                      'Load',
                                                                      'Currently consuming at 16 MW (90% capacity)'))
                                                          .addTo(mymap);
L.marker([33.2649, 126.5504], {icon: houseIcon}).bindPopup('<a href="analytics">My BEMS</a>' +
                                                          custom_overlay_fade('/public/live-mock-imgs/0.1.png',
                                                                      'Load',
                                                                      'Currently consuming at 8.3 kW (10% capacity)'))
                                                          .addTo(mymap);
L.marker([33.3649, 126.5504], {icon: batIcon}).bindPopup('<a href="analytics">My BAT</a>' +
                                                          custom_overlay_fade('/public/live-mock-imgs/0.8.png',
                                                                      'Load',
                                                                      'Currently consuming at 320 kW (80% capacity)'))
                                                          .addTo(mymap);


var popup = L.popup();

function custom_overlay_fade(p1, p2, p3) {
    image_overlay_fade = '<div class="my_container"><img src="' + p1 +
                         '" alt="' + p2 +
                         '" class="image"><div class="middle"><div class="text">' + p3 +
                         '</div></div></div>';
    return image_overlay_fade
}

function onMapClick(e) {
    popup
        .setLatLng(e.latlng)
        .setContent("You clicked the map at " + e.latlng.toString())
        .openOn(mymap);
}

// mymap.on('click', onMapClick);
