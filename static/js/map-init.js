
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

var windIcon = new LeafIcon({iconUrl: 'static/icons/wind.png'});
var houseIcon = new LeafIcon({iconUrl: 'static/icons/house.png'});
var batIcon = new LeafIcon({iconUrl: 'static/icons/battery.svg'});
var carIcon = new LeafIcon({iconUrl: 'static/icons/car.svg'});
var sunIcon = new LeafIcon({iconUrl: 'static/icons/sun.svg'});

//var opportunityWindIcon = new LeafIcon({iconUrl: 'static/icons/wind_opportunity.png'});
var opportunityWindIcon = new L.DivIcon({
                                            className: 'map-icon',
                                            html: '<i class="icon-wind"></i>',
                                            iconSize:     [24, 24], // size of the icon
                                            iconAnchor:   [12, 12], // point of the icon which will correspond to marker's location
                                            popupAnchor:  [0, -12] // point from which the popup should open relative to the iconAnchor
                                        });
var opportunityBatteryIcon = new LeafIcon({iconUrl: 'static/icons/battery_opportunity.png'});

function custom_overlay_fade(image, asset_name, asset_display_name, overlay_text) {
    return '<div class="my_container">' +
           '  <img src="' + image + '" alt="Current energy level for ' + asset_name + '" class="image">' +
           '    <div class="middle">' +
           '      <div class="text">' + overlay_text + '</div>' +
           '  </div>' +
           '</div>' +
           '<br/><button><a target="_blank" href="analytics?resource=' + asset_name + '">Analyze '+ asset_display_name +'</a></button>';
}
